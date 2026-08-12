"""Pose address を使って Maya animation clip を JSON 化する。"""

from __future__ import absolute_import

import json
import math
import os
import tempfile

import maya.cmds as cmds
import maya.mel as mel

from ywta.anim import pose_io
from ywta.core import undo_utils


FORMAT = "ywta.animation_clip"
VERSION = 1
ANIMATABLE_TYPES = pose_io.NUMERIC_TYPES | {"enum"}
TANGENT_TYPES = {
    "auto",
    "clamped",
    "fast",
    "fixed",
    "flat",
    "linear",
    "plateau",
    "slow",
    "smooth",
    "spline",
    "step",
    "stepnext",
}
MODE_OPTION = "ywtaClipLoadMode"
SELECTED_ONLY_OPTION = "ywtaClipLoadSelectedOnly"
START_ANCHOR_OPTION = "ywtaClipLoadStartAnchor"
END_ANCHOR_OPTION = "ywtaClipLoadEndAnchor"
TEMP_CLIP_FILENAME = "ywta_temp_animation_clip.json"
LOAD_MODES = ("place", "replace", "insert")


def get_load_settings():
    """optionVarから検証済みClip適用設定を取得する。"""
    mode = cmds.optionVar(query=MODE_OPTION) if cmds.optionVar(exists=MODE_OPTION) else "replace"
    selected_only = pose_io.option_bool(SELECTED_ONLY_OPTION, False)
    if mode not in LOAD_MODES:
        mode = "replace"
    return mode, selected_only


def set_load_settings(mode, selected_only):
    """検証済みClip適用設定をoptionVarへ保存する。"""
    if mode not in LOAD_MODES:
        raise ValueError("modeはplace / replace / insertのいずれかにしてください。")
    if not isinstance(selected_only, bool):
        raise ValueError("selected_onlyはboolにしてください。")
    cmds.optionVar(stringValue=(MODE_OPTION, mode))
    cmds.optionVar(intValue=(SELECTED_ONLY_OPTION, int(selected_only)))
    return mode, selected_only


def get_anchor_settings():
    """optionVarからclip境界anchorの適用設定を取得する。"""
    start_anchor = pose_io.option_bool(START_ANCHOR_OPTION, True)
    end_anchor = pose_io.option_bool(END_ANCHOR_OPTION, True)
    return start_anchor, end_anchor


def set_anchor_settings(start_anchor, end_anchor):
    """検証済みclip境界anchor設定をoptionVarへ保存する。"""
    if not isinstance(start_anchor, bool) or not isinstance(end_anchor, bool):
        raise ValueError("anchor設定はboolにしてください。")
    cmds.optionVar(intValue=(START_ANCHOR_OPTION, int(start_anchor)))
    cmds.optionVar(intValue=(END_ANCHOR_OPTION, int(end_anchor)))
    return start_anchor, end_anchor


def _finite_number(value, label):
    """bool ではない有限数を検証して float で返す。"""
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ValueError("{} は有限数で指定してください。".format(label))
    return float(value)


def _capture_channel(node, attribute, start, end):
    """指定範囲にキーがある scalar channel を取得する。"""
    plug = "{}.{}".format(node, attribute)
    if cmds.getAttr(plug, lock=True):
        return None
    attr_type = cmds.getAttr(plug, type=True)
    if attr_type not in ANIMATABLE_TYPES:
        return None
    incoming = cmds.listConnections(plug, source=True, destination=False, plugs=True) or []
    if not incoming or not all(cmds.nodeType(source.split(".", 1)[0]).startswith("animCurve") for source in incoming):
        return None
    times = cmds.keyframe(plug, query=True, time=(start, end), timeChange=True) or []
    values = cmds.keyframe(plug, query=True, time=(start, end), valueChange=True) or []
    if not times:
        return None
    in_tangents = cmds.keyTangent(plug, query=True, time=(start, end), inTangentType=True) or []
    out_tangents = cmds.keyTangent(plug, query=True, time=(start, end), outTangentType=True) or []
    in_angles = cmds.keyTangent(plug, query=True, time=(start, end), inAngle=True) or []
    out_angles = cmds.keyTangent(plug, query=True, time=(start, end), outAngle=True) or []
    in_weights = cmds.keyTangent(plug, query=True, time=(start, end), inWeight=True) or []
    out_weights = cmds.keyTangent(plug, query=True, time=(start, end), outWeight=True) or []
    counts = {
        len(times),
        len(values),
        len(in_tangents),
        len(out_tangents),
        len(in_angles),
        len(out_angles),
        len(in_weights),
        len(out_weights),
    }
    if len(counts) != 1:
        raise RuntimeError("keyframe と tangent の件数が一致しません: {}".format(plug))
    keys = []
    for values_at_key in zip(
        times,
        values,
        in_tangents,
        out_tangents,
        in_angles,
        out_angles,
        in_weights,
        out_weights,
    ):
        time, value, in_tangent, out_tangent, in_angle, out_angle, in_weight, out_weight = values_at_key
        numeric = (time, value, in_angle, out_angle, in_weight, out_weight)
        if not all(math.isfinite(float(item)) for item in numeric):
            raise ValueError("非有限の keyframe は保存できません: {}".format(plug))
        key = {
            "time": float(time) - start,
            "value": float(value),
            "in_tangent": in_tangent,
            "out_tangent": out_tangent,
            "in_angle": float(in_angle),
            "out_angle": float(out_angle),
            "in_weight": float(in_weight),
            "out_weight": float(out_weight),
        }
        if attr_type == "enum":
            key["enum_label"] = pose_io._enum_label(plug, value)
        keys.append(key)
    real_times = {float(time) for time in times}
    boundaries = ((start, "start", 0.0), (end, "end", end - start))
    for absolute_time, boundary, relative_time in boundaries:
        if absolute_time in real_times or (boundary == "end" and end == start):
            continue
        value = cmds.getAttr(plug, time=absolute_time)
        tangent = "step" if attr_type in {"enum", "bool"} else "auto"
        key = {
            "time": relative_time,
            "value": float(value),
            "in_tangent": tangent,
            "out_tangent": tangent,
            "in_angle": 0.0,
            "out_angle": 0.0,
            "in_weight": 1.0,
            "out_weight": 1.0,
            "synthetic_boundary": boundary,
        }
        if attr_type == "enum":
            key["enum_label"] = pose_io._enum_label(plug, value)
        keys.append(key)
    keys.sort(key=lambda item: item["time"])
    weighted = cmds.keyTangent(plug, query=True, weightedTangents=True) or [False]
    return {
        "name": attribute,
        "type": attr_type,
        "weighted_tangents": bool(weighted[0]),
        "keys": keys,
    }


def capture(nodes=None, start=None, end=None):
    """選択コントロールの animation keys を相対時間 clip にする。"""
    if start is None:
        start = cmds.playbackOptions(query=True, minTime=True)
    if end is None:
        end = cmds.playbackOptions(query=True, maxTime=True)
    start = _finite_number(start, "start")
    end = _finite_number(end, "end")
    if end < start:
        raise ValueError("end は start 以上にしてください。")

    controls = []
    addresses = set()
    for node in pose_io.resolve_controls(nodes):
        address = pose_io.control_address(node)
        if address in addresses:
            raise ValueError("Animation address が重複しています: {}".format(address))
        addresses.add(address)
        channels = []
        for attribute in cmds.listAttr(node, keyable=True, scalar=True) or []:
            channel = _capture_channel(node, attribute, start, end)
            if channel is not None:
                channels.append(channel)
        if channels:
            controls.append(
                {
                    "address": address,
                    "source_name": node.rsplit("|", 1)[-1],
                    "channels": channels,
                }
            )
    if not controls:
        raise ValueError("指定範囲に保存可能な animation key がありません。")
    return {
        "format": FORMAT,
        "version": VERSION,
        "duration": end - start,
        "time_unit": cmds.currentUnit(query=True, time=True),
        "linear_unit": cmds.currentUnit(query=True, linear=True),
        "angle_unit": cmds.currentUnit(query=True, angle=True),
        "controls": controls,
    }


def capture_time_range():
    """ハイライト範囲を優先し、なければplayback rangeを返す。

    Maya timeControlが返す現在time unitの開始・終了値を使用する。standaloneなど
    time sliderがない環境ではplayback rangeへ安全に戻る。
    """
    playback = (
        float(cmds.playbackOptions(query=True, minTime=True)),
        float(cmds.playbackOptions(query=True, maxTime=True)),
    )
    try:
        slider = mel.eval("$tmp = $gPlayBackSlider;")
        if not slider or not cmds.timeControl(slider, query=True, rangeVisible=True):
            return playback
        values = cmds.timeControl(slider, query=True, rangeArray=True) or []
    except RuntimeError:
        return playback
    if len(values) != 2:
        return playback
    start = float(values[0])
    end = float(values[1])
    if not math.isfinite(start) or not math.isfinite(end) or end <= start:
        return playback
    return start, end


def _validate(data):
    """外部 clip JSON を scene 編集前に完全検証する。"""
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError("YWTA Animation Clip ではありません。")
    if data.get("version") != VERSION:
        raise ValueError("未対応の Animation Clip version です: {}".format(data.get("version")))
    duration = _finite_number(data.get("duration"), "duration")
    if duration < 0.0:
        raise ValueError("duration は0以上にしてください。")
    for unit_name in ("time_unit", "linear_unit", "angle_unit"):
        if unit_name in data and (not isinstance(data[unit_name], str) or not data[unit_name]):
            raise ValueError("{}が不正です。".format(unit_name))
    controls = data.get("controls")
    if not isinstance(controls, list) or not controls:
        raise ValueError("controls がありません。")
    addresses = set()
    for control in controls:
        if not isinstance(control, dict) or not pose_io.is_control_address(control.get("address")):
            raise ValueError("control address が不正です。")
        address = control["address"]
        if address in addresses:
            raise ValueError("control address が不正または重複しています: {}".format(address))
        addresses.add(address)
        channels = control.get("channels")
        if not isinstance(channels, list) or not channels:
            raise ValueError("channels がありません: {}".format(address))
        channel_names = set()
        for channel in channels:
            if not isinstance(channel, dict):
                raise ValueError("channel が不正です: {}".format(address))
            name = channel.get("name")
            attr_type = channel.get("type")
            if not isinstance(name, str) or not name or name in channel_names:
                raise ValueError("channel 名が不正または重複しています: {}".format(address))
            channel_names.add(name)
            if attr_type not in ANIMATABLE_TYPES:
                raise ValueError("未対応の channel 型です: {}".format(attr_type))
            keys = channel.get("keys")
            if not isinstance(keys, list) or not keys:
                raise ValueError("keys がありません: {}.{}".format(address, name))
            if "weighted_tangents" in channel and not isinstance(channel["weighted_tangents"], bool):
                raise ValueError("weighted tangent設定が不正です: {}.{}".format(address, name))
            previous_time = None
            for key in keys:
                if not isinstance(key, dict):
                    raise ValueError("key が不正です: {}.{}".format(address, name))
                time = _finite_number(key.get("time"), "key time")
                boundary = key.get("synthetic_boundary")
                if boundary not in {None, "start", "end"}:
                    raise ValueError("synthetic boundaryが不正です: {}.{}".format(address, name))
                if boundary == "start" and time != 0.0 or boundary == "end" and time != duration:
                    raise ValueError("synthetic boundary時刻が不正です: {}.{}".format(address, name))
                key_value = _finite_number(key.get("value"), "key value")
                if attr_type == "enum" and not float(key_value).is_integer():
                    raise ValueError("enum key値は整数indexにしてください: {}.{}".format(address, name))
                tangent_values = ("in_angle", "out_angle", "in_weight", "out_weight")
                present_values = [value_name in key for value_name in tangent_values]
                if any(present_values) and not all(present_values):
                    raise ValueError("tangent値が不足しています: {}.{}".format(address, name))
                for value_name in tangent_values:
                    if value_name in key:
                        _finite_number(key[value_name], value_name)
                if (
                    attr_type == "enum"
                    and "enum_label" in key
                    and (not isinstance(key["enum_label"], str) or not key["enum_label"])
                ):
                    raise ValueError("enum labelが不正です: {}.{}".format(address, name))
                if time < 0.0 or time > duration or (previous_time is not None and time <= previous_time):
                    raise ValueError("key time の範囲または順序が不正です: {}.{}".format(address, name))
                previous_time = time
                if key.get("in_tangent") not in TANGENT_TYPES or key.get("out_tangent") not in TANGENT_TYPES:
                    raise ValueError("tangent type が不正です: {}.{}".format(address, name))
    return data


def save(nodes, file_path, start=None, end=None):
    """Animation clip を JSON へ原子的に保存する。"""
    data = capture(nodes, start=start, end=end)
    target = os.path.abspath(file_path)
    directory = os.path.dirname(target)
    if not os.path.isdir(directory):
        raise ValueError("保存先ディレクトリがありません: {}".format(directory))
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=directory, prefix=".ywta_clip_", suffix=".tmp", delete=False
    )
    temporary = handle.name
    try:
        with handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, target)
    except Exception:
        if os.path.exists(temporary):
            os.remove(temporary)
        raise
    return target


def read(file_path):
    """Animation Clip JSON を読み込み、検証済み辞書を返す。"""
    with open(file_path, "r", encoding="utf-8") as handle:
        return _validate(json.load(handle))


def temp_clip_path():
    """Mayaユーザー用の一時Animation Clip JSONパスを返す。"""
    return os.path.join(cmds.internalVar(userAppDir=True), TEMP_CLIP_FILENAME)


def save_temp(nodes, file_path=None, start=None, end=None):
    """animation clipを固定または指定の一時JSONへ保存する。"""
    return save(
        nodes,
        file_path or temp_clip_path(),
        start=start,
        end=end,
    )


def load_temp(
    nodes=None,
    file_path=None,
    mode="replace",
    apply_start_anchor=True,
    apply_end_anchor=True,
):
    """一時Clip JSONを既存の検証済み適用経路でロードする。"""
    return apply(
        read(file_path or temp_clip_path()),
        nodes=nodes,
        mode=mode,
        apply_start_anchor=apply_start_anchor,
        apply_end_anchor=apply_end_anchor,
    )


def _apply_mode(mode, replace):
    """新旧引数から clip 適用モードを解決する。"""
    if mode is None:
        if not isinstance(replace, bool):
            raise ValueError("replaceはboolにしてください。")
        return "replace" if replace else "place"
    if mode not in {"place", "replace", "insert"}:
        raise ValueError("mode は place / replace / insert のいずれかにしてください。")
    return mode


def _shift_keys_for_insert(nodes, start_time, offset):
    """対象controlの開始時刻以降の全キーを指定量だけ後ろへ移動する。"""
    shifted = 0
    for node in nodes:
        times = cmds.keyframe(node, query=True, timeChange=True) or []
        source_times = sorted({float(time) for time in times if time >= start_time}, reverse=True)
        for time in source_times:
            shifted += cmds.keyframe(
                node,
                edit=True,
                time=(time, time),
                relative=True,
                timeChange=offset,
            )
    return shifted


def _weighted_tangent_conflict(plug, channel, mode, start_time, end_time):
    """curve全体のweighted modeが範囲外キーを変える場合はTrueを返す。"""
    if "weighted_tangents" not in channel:
        return False
    times = [float(time) for time in (cmds.keyframe(plug, query=True, timeChange=True) or [])]
    if not times:
        return False
    current = bool((cmds.keyTangent(plug, query=True, weightedTangents=True) or [False])[0])
    if current == channel["weighted_tangents"]:
        return False
    return mode != "replace" or any(time < start_time or time > end_time for time in times)


def apply(
    data,
    nodes=None,
    start_time=None,
    replace=True,
    mode=None,
    apply_start_anchor=True,
    apply_end_anchor=True,
):
    """Animation clip を namespace 非依存で適用する。

    Args:
        data: :func:`capture` または :func:`read` の辞書。
        nodes: 適用対象を限定するコントロール。None は scene 全体。
        start_time: clip の開始フレーム。None は現在フレーム。
        replace: 後方互換引数。mode 未指定時に True は replace、False は place。
        mode: place / replace / insert。insert は解決済みcontrolの全キーを
            clipの占有フレーム数だけ後ろへ移動してから適用する。

    Returns:
        applied_channels / applied_keys / skipped を持つ結果辞書。
    """
    data = _validate(data)
    mode = _apply_mode(mode, replace)
    if not isinstance(apply_start_anchor, bool) or not isinstance(apply_end_anchor, bool):
        raise ValueError("anchor適用設定はboolにしてください。")
    if start_time is None:
        start_time = cmds.currentTime(query=True)
    start_time = _finite_number(start_time, "start_time")
    index, ambiguous = pose_io.target_index(nodes)
    operations = []
    resolved_nodes = set()
    skipped = []
    for control in data["controls"]:
        address = control["address"]
        if address in ambiguous:
            raise ValueError("target Animation address が曖昧です: {}".format(address))
        node = index.get(address)
        if node is None:
            skipped.append({"address": address, "reason": "target_missing"})
            continue
        for channel in control["channels"]:
            attribute = channel["name"]
            plug = "{}.{}".format(node, attribute)
            if not cmds.objExists(plug) or cmds.getAttr(plug, lock=True) or not cmds.getAttr(plug, keyable=True):
                skipped.append({"address": address, "attribute": attribute, "reason": "unavailable"})
                continue
            if cmds.getAttr(plug, type=True) != channel["type"]:
                skipped.append({"address": address, "attribute": attribute, "reason": "type_mismatch"})
                continue
            incoming = cmds.listConnections(plug, source=True, destination=False, plugs=True) or []
            if incoming and not all(cmds.nodeType(source.split(".", 1)[0]).startswith("animCurve") for source in incoming):
                skipped.append({"address": address, "attribute": attribute, "reason": "driven"})
                continue
            if channel["type"] == "enum":
                for key in channel["keys"]:
                    if key.get("synthetic_boundary") == "start" and not apply_start_anchor:
                        continue
                    if key.get("synthetic_boundary") == "end" and not apply_end_anchor:
                        continue
                    if "enum_label" in key:
                        pose_io._enum_index(plug, key["enum_label"])
                    else:
                        pose_io._enum_label(plug, key["value"])
            operations.append((plug, channel, address))

    end_time = start_time + data["duration"]
    safe_operations = []
    for plug, channel, address in operations:
        if _weighted_tangent_conflict(plug, channel, mode, start_time, end_time):
            skipped.append(
                {
                    "address": address,
                    "attribute": channel["name"],
                    "reason": "weighted_tangent_conflict",
                }
            )
            continue
        safe_operations.append((plug, channel))
        resolved_nodes.add(plug.split(".", 1)[0])
    operations = safe_operations

    if not operations:
        scene_units = {
            "time_unit": cmds.currentUnit(query=True, time=True),
            "linear_unit": cmds.currentUnit(query=True, linear=True),
            "angle_unit": cmds.currentUnit(query=True, angle=True),
        }
        unit_mismatches = [key for key in scene_units if data.get(key) and data[key] != scene_units[key]]
        return {
            "applied_channels": 0,
            "applied_keys": 0,
            "shifted_keys": 0,
            "insert_offset": 0.0,
            "mode": mode,
            "source_time_unit": data.get("time_unit"),
            "scene_time_unit": scene_units["time_unit"],
            "time_unit_mismatch": "time_unit" in unit_mismatches,
            "unit_mismatches": unit_mismatches,
            "source_units": {key: data.get(key) for key in scene_units},
            "scene_units": scene_units,
            "skipped": skipped,
        }

    undo_utils.require_enabled("Animation Clip Apply")
    cmds.undoInfo(openChunk=True, chunkName="YWTA Animation Clip Apply")
    failed = False
    applied_keys = 0
    try:
        shifted_keys = 0
        insert_offset = 0.0
        if mode == "insert":
            insert_offset = data["duration"] + 1.0
            shifted_keys = _shift_keys_for_insert(sorted(resolved_nodes), start_time, insert_offset)
        for plug, channel in operations:
            if mode == "replace":
                cmds.cutKey(plug, time=(start_time, end_time), clear=True)
            keys = [
                key
                for key in channel["keys"]
                if not (key.get("synthetic_boundary") == "start" and not apply_start_anchor)
                and not (key.get("synthetic_boundary") == "end" and not apply_end_anchor)
            ]
            for key in keys:
                time = start_time + key["time"]
                value = (
                    pose_io._enum_index(plug, key["enum_label"])
                    if channel["type"] == "enum" and "enum_label" in key
                    else key["value"]
                )
                cmds.setKeyframe(plug, time=time, value=value)
                applied_keys += 1
            if "weighted_tangents" in channel:
                cmds.keyTangent(
                    plug,
                    edit=True,
                    weightedTangents=channel["weighted_tangents"],
                )
            for key in keys:
                time = start_time + key["time"]
                cmds.keyTangent(
                    plug,
                    edit=True,
                    time=(time, time),
                    inTangentType=key["in_tangent"],
                    outTangentType=key["out_tangent"],
                )
                tangent_kwargs = {}
                if key["in_tangent"] == "fixed" and "in_angle" in key:
                    tangent_kwargs["inAngle"] = key["in_angle"]
                    if channel.get("weighted_tangents"):
                        tangent_kwargs["inWeight"] = key["in_weight"]
                if key["out_tangent"] == "fixed" and "out_angle" in key:
                    tangent_kwargs["outAngle"] = key["out_angle"]
                    if channel.get("weighted_tangents"):
                        tangent_kwargs["outWeight"] = key["out_weight"]
                if tangent_kwargs:
                    cmds.keyTangent(plug, edit=True, time=(time, time), **tangent_kwargs)
        if operations:
            cmds.dgdirty([plug for plug, _channel in operations])
    except Exception:
        failed = True
        raise
    finally:
        cmds.undoInfo(closeChunk=True)
        if failed:
            cmds.undo()
    scene_units = {
        "time_unit": cmds.currentUnit(query=True, time=True),
        "linear_unit": cmds.currentUnit(query=True, linear=True),
        "angle_unit": cmds.currentUnit(query=True, angle=True),
    }
    unit_mismatches = [key for key in scene_units if data.get(key) and data[key] != scene_units[key]]
    return {
        "applied_channels": len(operations),
        "applied_keys": applied_keys,
        "shifted_keys": shifted_keys,
        "insert_offset": insert_offset,
        "mode": mode,
        "source_time_unit": data.get("time_unit"),
        "scene_time_unit": scene_units["time_unit"],
        "time_unit_mismatch": "time_unit" in unit_mismatches,
        "unit_mismatches": unit_mismatches,
        "source_units": {key: data.get(key) for key in scene_units},
        "scene_units": scene_units,
        "skipped": skipped,
    }


def save_selected():
    """選択コントロールのhighlight/playback rangeを保存する。"""
    selected = pose_io.resolve_controls()
    paths = cmds.fileDialog2(fileMode=0, dialogStyle=2, caption="Save Animation Clip", fileFilter="JSON (*.json)")
    if not paths:
        return None
    start, end = capture_time_range()
    return save(selected, paths[0], start=start, end=end)


def save_temp_selected():
    """選択controlのhighlight/playback rangeを一時Clip JSONへ保存する。"""
    selected = pose_io.resolve_controls()
    start, end = capture_time_range()
    path = save_temp(selected, start=start, end=end)
    cmds.inViewMessage(
        statusMessage="Saved temporary animation clip.",
        position="topCenter",
        fade=True,
    )
    return path


def load_temp_with_settings():
    """保存済みMode/Selected-only/anchor設定で一時Clipを適用する。"""
    mode, selected_only = get_load_settings()
    start_anchor, end_anchor = get_anchor_settings()
    selected = pose_io.resolve_controls() if selected_only else None
    result = load_temp(
        nodes=selected,
        mode=mode,
        apply_start_anchor=start_anchor,
        apply_end_anchor=end_anchor,
    )
    if result["unit_mismatches"]:
        cmds.warning(
            "Animation Clip unit mismatch {}; raw値・rawフレームで適用しました。".format(", ".join(result["unit_mismatches"]))
        )
    return result


def load_clip(
    selected_only=False,
    mode="replace",
    apply_start_anchor=True,
    apply_end_anchor=True,
):
    """ダイアログで選んだ clip を現在フレームから適用する。"""
    selected = pose_io.resolve_controls() if selected_only else None
    paths = cmds.fileDialog2(fileMode=1, dialogStyle=2, caption="Load Animation Clip", fileFilter="JSON (*.json)")
    if not paths:
        return None
    result = apply(
        read(paths[0]),
        nodes=selected,
        mode=mode,
        apply_start_anchor=apply_start_anchor,
        apply_end_anchor=apply_end_anchor,
    )
    if result["unit_mismatches"]:
        cmds.warning(
            "Animation Clip unit mismatch {}; raw値・rawフレームで適用しました。".format(", ".join(result["unit_mismatches"]))
        )
    return result


def load_clip_with_settings():
    """保存済みMode/Selected-only設定でClipファイルを適用する。"""
    mode, selected_only = get_load_settings()
    start_anchor, end_anchor = get_anchor_settings()
    return load_clip(
        selected_only=selected_only,
        mode=mode,
        apply_start_anchor=start_anchor,
        apply_end_anchor=end_anchor,
    )


def show_load_options():
    """ClipのModeとSelected-onlyを設定して適用するUIを表示する。"""
    window = "ywtaClipLoadOptionsWindow"
    if cmds.window(window, exists=True):
        cmds.deleteUI(window)
    mode, selected_only = get_load_settings()
    cmds.window(window, title="YWTA Load Animation Clip", sizeable=False)
    cmds.columnLayout(adjustableColumn=True, rowSpacing=8, width=380)
    mode_field = cmds.optionMenuGrp(label="Mode")
    labels = {"place": "Place", "replace": "Replace", "insert": "Insert"}
    for value in LOAD_MODES:
        cmds.menuItem(label=labels[value])
    cmds.optionMenuGrp(mode_field, edit=True, value=labels[mode])
    selected_field = cmds.checkBox(
        label="Apply to selected controls only",
        value=selected_only,
    )
    start_anchor, end_anchor = get_anchor_settings()
    start_anchor_field = cmds.checkBox(
        label="Apply synthetic start anchors",
        value=start_anchor,
    )
    end_anchor_field = cmds.checkBox(
        label="Apply synthetic end anchors",
        value=end_anchor,
    )

    def apply_options(*_args):
        inverse_labels = {label: value for value, label in labels.items()}
        set_load_settings(
            inverse_labels[cmds.optionMenuGrp(mode_field, query=True, value=True)],
            cmds.checkBox(selected_field, query=True, value=True),
        )
        set_anchor_settings(
            cmds.checkBox(start_anchor_field, query=True, value=True),
            cmds.checkBox(end_anchor_field, query=True, value=True),
        )
        return load_clip_with_settings()

    cmds.button(label="Load Animation Clip...", command=apply_options)
    cmds.showWindow(window)
    return window
