"""Pose address を使って Maya animation clip を JSON 化する。"""

from __future__ import absolute_import

import json
import math
import os
import tempfile

import maya.cmds as cmds

from ywta.anim import pose_io


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
    if not (len(times) == len(values) == len(in_tangents) == len(out_tangents)):
        raise RuntimeError("keyframe と tangent の件数が一致しません: {}".format(plug))
    keys = []
    for time, value, in_tangent, out_tangent in zip(times, values, in_tangents, out_tangents):
        if not math.isfinite(float(time)) or not math.isfinite(float(value)):
            raise ValueError("非有限の keyframe は保存できません: {}".format(plug))
        keys.append(
            {
                "time": float(time) - start,
                "value": float(value),
                "in_tangent": in_tangent,
                "out_tangent": out_tangent,
            }
        )
    return {"name": attribute, "type": attr_type, "keys": keys}


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
        "controls": controls,
    }


def _validate(data):
    """外部 clip JSON を scene 編集前に完全検証する。"""
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError("YWTA Animation Clip ではありません。")
    if data.get("version") != VERSION:
        raise ValueError("未対応の Animation Clip version です: {}".format(data.get("version")))
    duration = _finite_number(data.get("duration"), "duration")
    if duration < 0.0:
        raise ValueError("duration は0以上にしてください。")
    controls = data.get("controls")
    if not isinstance(controls, list) or not controls:
        raise ValueError("controls がありません。")
    addresses = set()
    for control in controls:
        if not isinstance(control, dict) or not isinstance(control.get("address"), str):
            raise ValueError("control address が不正です。")
        address = control["address"]
        if not address.startswith(("id:", "name:")) or address in addresses:
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
            previous_time = None
            for key in keys:
                if not isinstance(key, dict):
                    raise ValueError("key が不正です: {}.{}".format(address, name))
                time = _finite_number(key.get("time"), "key time")
                _finite_number(key.get("value"), "key value")
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


def apply(data, nodes=None, start_time=None, replace=True):
    """Animation clip を namespace 非依存で適用する。

    Args:
        data: :func:`capture` または :func:`read` の辞書。
        nodes: 適用対象を限定するコントロール。None は scene 全体。
        start_time: clip の開始フレーム。None は現在フレーム。
        replace: True の場合、clip 範囲内の既存キーを先に削除する。

    Returns:
        applied_channels / applied_keys / skipped を持つ結果辞書。
    """
    data = _validate(data)
    if start_time is None:
        start_time = cmds.currentTime(query=True)
    start_time = _finite_number(start_time, "start_time")
    index, ambiguous = pose_io.target_index(nodes)
    operations = []
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
            if not cmds.objExists(plug) or cmds.getAttr(plug, lock=True):
                skipped.append({"address": address, "attribute": attribute, "reason": "unavailable"})
                continue
            if cmds.getAttr(plug, type=True) != channel["type"]:
                skipped.append({"address": address, "attribute": attribute, "reason": "type_mismatch"})
                continue
            incoming = cmds.listConnections(plug, source=True, destination=False, plugs=True) or []
            if incoming and not all(cmds.nodeType(source.split(".", 1)[0]).startswith("animCurve") for source in incoming):
                skipped.append({"address": address, "attribute": attribute, "reason": "driven"})
                continue
            operations.append((plug, channel))

    cmds.undoInfo(openChunk=True, chunkName="YWTA Animation Clip Apply")
    failed = False
    applied_keys = 0
    try:
        end_time = start_time + data["duration"]
        for plug, channel in operations:
            if replace:
                cmds.cutKey(plug, time=(start_time, end_time), clear=True)
            for key in channel["keys"]:
                time = start_time + key["time"]
                cmds.setKeyframe(plug, time=time, value=key["value"])
                cmds.keyTangent(
                    plug,
                    edit=True,
                    time=(time, time),
                    inTangentType=key["in_tangent"],
                    outTangentType=key["out_tangent"],
                )
                applied_keys += 1
        if operations:
            cmds.dgdirty([plug for plug, _channel in operations])
    except Exception:
        failed = True
        raise
    finally:
        cmds.undoInfo(closeChunk=True)
        if failed:
            cmds.undo()
    return {
        "applied_channels": len(operations),
        "applied_keys": applied_keys,
        "skipped": skipped,
    }


def save_selected():
    """選択コントロールの playback range をダイアログで保存する。"""
    selected = pose_io.resolve_controls()
    paths = cmds.fileDialog2(fileMode=0, dialogStyle=2, caption="Save Animation Clip", fileFilter="JSON (*.json)")
    if not paths:
        return None
    return save(selected, paths[0])


def load_clip(selected_only=False):
    """ダイアログで選んだ clip を現在フレームから適用する。"""
    selected = pose_io.resolve_controls() if selected_only else None
    paths = cmds.fileDialog2(fileMode=1, dialogStyle=2, caption="Load Animation Clip", fileFilter="JSON (*.json)")
    if not paths:
        return None
    return apply(read(paths[0]), nodes=selected)
