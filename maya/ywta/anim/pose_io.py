"""namespace を跨いで利用できる Maya ポーズ JSON の保存・適用。"""

from __future__ import absolute_import

import json
import math
import os
import tempfile

import maya.cmds as cmds

from ywta.core import undo_utils


FORMAT = "ywta.pose"
VERSION = 1
POSE_ID_ATTRIBUTE = "ywtaPoseId"
BLEND_OPTION = "ywtaPoseLoadBlend"
SELECTED_ONLY_OPTION = "ywtaPoseLoadSelectedOnly"
TEMP_POSE_FILENAME = "ywta_temp_pose.json"
NUMERIC_TYPES = {
    "double",
    "doubleAngle",
    "doubleLinear",
    "float",
    "long",
    "short",
    "byte",
    "bool",
}
INTEGER_TYPES = {"long", "short", "byte"}


def option_bool(name, default):
    """optionVarを0/1だけ許可するboolとして読み込む。"""
    if not isinstance(name, str) or not name or not isinstance(default, bool):
        raise ValueError("option boolのname/defaultが不正です。")
    raw = cmds.optionVar(query=name) if cmds.optionVar(exists=name) else default
    return bool(raw) if isinstance(raw, (bool, int)) and raw in {0, 1} else default


def get_load_settings():
    """optionVarから検証済みPose適用設定を取得する。"""
    blend = cmds.optionVar(query=BLEND_OPTION) if cmds.optionVar(exists=BLEND_OPTION) else 1.0
    selected_only = option_bool(SELECTED_ONLY_OPTION, False)
    if not isinstance(blend, (int, float)) or isinstance(blend, bool) or not math.isfinite(blend) or not 0.0 <= blend <= 1.0:
        blend = 1.0
    return float(blend), selected_only


def set_load_settings(blend, selected_only):
    """検証済みPose適用設定をoptionVarへ保存する。"""
    if not isinstance(blend, (int, float)) or isinstance(blend, bool) or not math.isfinite(blend) or not 0.0 <= blend <= 1.0:
        raise ValueError("blendは0.0以上1.0以下の有限値にしてください。")
    if not isinstance(selected_only, bool):
        raise ValueError("selected_onlyはboolにしてください。")
    blend = float(blend)
    cmds.optionVar(floatValue=(BLEND_OPTION, blend))
    cmds.optionVar(intValue=(SELECTED_ONLY_OPTION, int(selected_only)))
    return blend, selected_only


def _long_nodes(nodes=None):
    """対象ノードを順序保持したロングパスへ解決する。"""
    source = nodes if nodes is not None else cmds.ls(selection=True, long=True)
    if isinstance(source, str):
        source = [source]
    if not source:
        raise ValueError("ポーズ対象のコントロールを選択してください。")
    result = []
    seen = set()
    for node in source:
        matches = cmds.ls(node, long=True) or []
        if len(matches) != 1:
            raise ValueError("コントロールを一意に解決できません: {}".format(node))
        node_uuid = (cmds.ls(matches[0], uuid=True) or [None])[0]
        if node_uuid is None:
            raise ValueError("コントロールのUUIDを取得できません: {}".format(node))
        if node_uuid not in seen:
            seen.add(node_uuid)
            result.append(matches[0])
    return result


def _base_name(node):
    """DAG パスと namespace を除いたノード名を返す。"""
    return node.rsplit("|", 1)[-1].rsplit(":", 1)[-1]


def _address(node):
    """明示 ID を優先し、なければ namespace 非依存名を返す。"""
    plug = "{}.{}".format(node, POSE_ID_ATTRIBUTE)
    if cmds.objExists(plug) and cmds.getAttr(plug, type=True) == "string":
        value = cmds.getAttr(plug)
        if isinstance(value, str) and value.strip():
            address = "id:" + value.strip()
            if not is_control_address(address):
                raise ValueError("Pose ID に制御文字は使用できません: {}".format(node))
            return address
    return "name:" + _base_name(node)


def resolve_controls(nodes=None):
    """Pose/Clip 対象を順序保持したロングパスへ解決する。"""
    return _long_nodes(nodes)


def control_address(node):
    """Pose/Clip 共通の namespace 非依存アドレスを返す。"""
    return _address(node)


def is_control_address(address):
    """portable control addressがprefixと非空値を持つか判定する。"""
    if not isinstance(address, str):
        return False
    prefix, separator, value = address.partition(":")
    return bool(
        separator
        and prefix in {"id", "name"}
        and value
        and value == value.strip()
        and not any(ord(character) < 32 or ord(character) == 127 for character in value)
    )


def set_pose_id(node, pose_id):
    """コントロールへ rig 間で安定した Pose ID を設定する。"""
    if not isinstance(pose_id, str) or not pose_id.strip():
        raise ValueError("Pose ID が空です。")
    pose_id = pose_id.strip()
    if not is_control_address("id:" + pose_id):
        raise ValueError("Pose ID に制御文字は使用できません。")
    matches = cmds.ls(node, long=True) or []
    if len(matches) != 1:
        raise ValueError("ノードを一意に解決できません: {}".format(node))
    if cmds.referenceQuery(matches[0], isNodeReferenced=True):
        raise ValueError("参照controlへPose IDは設定できません: {}".format(matches[0]))
    plug = "{}.{}".format(matches[0], POSE_ID_ATTRIBUTE)
    if cmds.objExists(plug) and cmds.getAttr(plug, type=True) != "string":
        raise ValueError("既存Pose ID属性がstringではありません: {}".format(plug))
    if cmds.objExists(plug) and not cmds.getAttr(plug, settable=True):
        raise ValueError("既存Pose ID属性を編集できません: {}".format(plug))
    undo_utils.require_enabled("Set Pose ID")
    cmds.undoInfo(openChunk=True, chunkName="YWTA Set Pose ID")
    failed = False
    try:
        if not cmds.objExists(plug):
            cmds.addAttr(matches[0], longName=POSE_ID_ATTRIBUTE, dataType="string")
        cmds.setAttr(plug, pose_id, type="string")
    except Exception:
        failed = True
        raise
    finally:
        cmds.undoInfo(closeChunk=True)
        if failed:
            cmds.undo()
    return plug


def set_pose_id_selected():
    """選択control 1つへダイアログからPose IDを設定する。"""
    selected = cmds.ls(selection=True, objectsOnly=True, long=True) or []
    controls = _long_nodes(selected)
    if len(controls) != 1 or not cmds.objectType(controls[0], isAType="transform"):
        raise ValueError("Pose IDを設定するcontrolを1つ選択してください。")
    plug = "{}.{}".format(controls[0], POSE_ID_ATTRIBUTE)
    current = ""
    if cmds.objExists(plug) and cmds.getAttr(plug, type=True) == "string":
        current = cmds.getAttr(plug) or ""
    result = cmds.promptDialog(
        title="Set Pose ID",
        message="Pose ID:",
        text=current,
        button=["Set", "Cancel"],
        defaultButton="Set",
        cancelButton="Cancel",
        dismissString="Cancel",
    )
    if result != "Set":
        return None
    return set_pose_id(controls[0], cmds.promptDialog(query=True, text=True))


def _capture_attribute(node, attribute):
    """対応する keyable scalar 属性を JSON 値へ変換する。"""
    plug = "{}.{}".format(node, attribute)
    if cmds.getAttr(plug, lock=True):
        return None
    incoming = cmds.listConnections(plug, source=True, destination=False, plugs=True) or []
    if incoming and not all(cmds.nodeType(source.split(".", 1)[0]).startswith("animCurve") for source in incoming):
        return None
    attr_type = cmds.getAttr(plug, type=True)
    if attr_type == "enum":
        return {"name": attribute, "type": attr_type, "value": cmds.getAttr(plug, asString=True)}
    if attr_type not in NUMERIC_TYPES:
        return None
    value = cmds.getAttr(plug)
    if not isinstance(value, (int, float)) or isinstance(value, bool) and attr_type != "bool":
        return None
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("非有限値は保存できません: {}".format(plug))
    return {"name": attribute, "type": attr_type, "value": value}


def capture(nodes=None):
    """選択コントロールのポーズをシリアライズ可能な辞書へ変換する。"""
    controls = []
    addresses = set()
    for node in _long_nodes(nodes):
        address = _address(node)
        if address in addresses:
            raise ValueError("Pose address が重複しています: {}".format(address))
        addresses.add(address)
        attributes = []
        for attribute in cmds.listAttr(node, keyable=True, scalar=True) or []:
            value = _capture_attribute(node, attribute)
            if value is not None:
                attributes.append(value)
        if attributes:
            controls.append(
                {
                    "address": address,
                    "source_name": node.rsplit("|", 1)[-1],
                    "attributes": attributes,
                }
            )
    if not controls:
        raise ValueError("保存可能な keyable 属性がありません。")
    return {
        "format": FORMAT,
        "version": VERSION,
        "linear_unit": cmds.currentUnit(query=True, linear=True),
        "angle_unit": cmds.currentUnit(query=True, angle=True),
        "controls": controls,
    }


def _validate(data):
    """外部 JSON を scene 編集前に完全検証する。"""
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError("YWTA Pose ファイルではありません。")
    if not isinstance(data.get("version"), int) or isinstance(data.get("version"), bool) or data["version"] != VERSION:
        raise ValueError("未対応の Pose version です: {}".format(data.get("version")))
    for unit_name in ("linear_unit", "angle_unit"):
        if unit_name in data and (not isinstance(data[unit_name], str) or not data[unit_name]):
            raise ValueError("{}が不正です。".format(unit_name))
    controls = data.get("controls")
    if not isinstance(controls, list) or not controls:
        raise ValueError("controls がありません。")
    addresses = set()
    for control in controls:
        if not isinstance(control, dict) or not is_control_address(control.get("address")):
            raise ValueError("control address が不正です。")
        address = control["address"]
        if address in addresses:
            raise ValueError("control address が不正または重複しています: {}".format(address))
        addresses.add(address)
        attributes = control.get("attributes")
        if not isinstance(attributes, list) or not attributes:
            raise ValueError("control attributes がありません: {}".format(address))
        names = set()
        for attribute in attributes:
            if not isinstance(attribute, dict):
                raise ValueError("attribute が不正です: {}".format(address))
            name = attribute.get("name")
            attr_type = attribute.get("type")
            value = attribute.get("value")
            if not isinstance(name, str) or not name or name in names:
                raise ValueError("attribute 名が不正または重複しています: {}".format(address))
            names.add(name)
            if attr_type == "enum":
                if not isinstance(value, str):
                    raise ValueError("enum 値が不正です: {}.{}".format(address, name))
            elif attr_type in NUMERIC_TYPES:
                if attr_type == "bool":
                    valid = isinstance(value, bool)
                elif attr_type in INTEGER_TYPES:
                    valid = isinstance(value, int) and not isinstance(value, bool)
                else:
                    valid = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))
                if not valid:
                    raise ValueError("数値が不正です: {}.{}".format(address, name))
            else:
                raise ValueError("未対応の属性型です: {}".format(attr_type))
    return data


def save(nodes, file_path):
    """選択ポーズを JSON へ原子的に保存する。"""
    data = capture(nodes)
    target = os.path.abspath(file_path)
    directory = os.path.dirname(target)
    if not os.path.isdir(directory):
        raise ValueError("保存先ディレクトリがありません: {}".format(directory))
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=directory, prefix=".ywta_pose_", suffix=".tmp", delete=False
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
    """Pose JSON を読み込み、検証済み辞書を返す。"""
    with open(file_path, "r", encoding="utf-8") as handle:
        return _validate(json.load(handle))


def temp_pose_path():
    """Mayaユーザー用の一時Pose JSONパスを返す。"""
    return os.path.join(cmds.internalVar(userAppDir=True), TEMP_POSE_FILENAME)


def save_temp(nodes, file_path=None):
    """control poseを固定または指定の一時JSONへ保存する。"""
    return save(nodes, file_path or temp_pose_path())


def load_temp(nodes=None, blend=1.0, file_path=None):
    """一時Pose JSONを既存の検証済み適用経路でロードする。"""
    return apply(read(file_path or temp_pose_path()), nodes=nodes, blend=blend)


def _target_index(nodes=None):
    """適用範囲の address から node への一意な index を作る。"""
    if nodes is None:
        candidates = cmds.ls(type=["transform", "joint"], long=True) or []
    else:
        candidates = _long_nodes(nodes)
    index = {}
    ambiguous = set()
    for node in candidates:
        address = _address(node)
        if address in index:
            ambiguous.add(address)
        else:
            index[address] = node
    for address in ambiguous:
        index.pop(address, None)
    return index, ambiguous


def target_index(nodes=None):
    """Pose/Clip 適用対象の一意アドレス index と曖昧アドレスを返す。"""
    return _target_index(nodes)


def _enum_index(plug, label):
    """enum 表示名から index を解決する。"""
    labels = cmds.attributeQuery(plug.rsplit(".", 1)[-1], node=plug.rsplit(".", 1)[0], listEnum=True)
    current_index = -1
    for item in labels[0].split(":") if labels else []:
        if "=" in item:
            item_label, explicit_index = item.rsplit("=", 1)
            current_index = int(explicit_index)
        else:
            item_label = item
            current_index += 1
        if item_label == label:
            return current_index
    raise ValueError("enum label がありません: {} = {}".format(plug, label))


def _enum_label(plug, value):
    """enum indexから表示名を解決する。"""
    labels = cmds.attributeQuery(plug.rsplit(".", 1)[-1], node=plug.rsplit(".", 1)[0], listEnum=True)
    current_index = -1
    for item in labels[0].split(":") if labels else []:
        if "=" in item:
            item_label, explicit_index = item.rsplit("=", 1)
            current_index = int(explicit_index)
        else:
            item_label = item
            current_index += 1
        if current_index == int(round(value)):
            return item_label
    raise ValueError("enum indexに表示名がありません: {} = {}".format(plug, value))


def _blended_value(current, saved, attr_type, blend):
    """属性型に応じた blend 値を返す。"""
    if attr_type in INTEGER_TYPES:
        return int(round(current + (saved - current) * blend))
    if attr_type == "bool":
        return bool(saved) if blend >= 0.5 else bool(current)
    return current + (saved - current) * blend


def apply(data, nodes=None, blend=1.0):
    """ポーズを scene 全体または指定コントロールへ一括 Undo で適用する。

    Args:
        data: :func:`capture` または :func:`read` の辞書。
        nodes: 適用対象を限定するノード。None は scene の transform 全体。
        blend: 現在値から保存値へ寄せる 0.0～1.0 の係数。

    Returns:
        applied / skipped 件数と理由の辞書。
    """
    data = _validate(data)
    if not isinstance(blend, (int, float)) or isinstance(blend, bool) or not math.isfinite(blend):
        raise ValueError("blend は 0.0～1.0 の有限値にしてください。")
    if blend < 0.0 or blend > 1.0:
        raise ValueError("blend は 0.0～1.0 にしてください。")
    scene_units = {
        "linear_unit": cmds.currentUnit(query=True, linear=True),
        "angle_unit": cmds.currentUnit(query=True, angle=True),
    }
    unit_mismatches = [key for key in scene_units if data.get(key) and data[key] != scene_units[key]]
    if blend == 0.0:
        return {
            "applied": 0,
            "skipped": [],
            "unit_mismatches": unit_mismatches,
            "source_units": {key: data.get(key) for key in scene_units},
            "scene_units": scene_units,
        }
    index, ambiguous = _target_index(nodes)
    operations = []
    skipped = []
    for control in data["controls"]:
        address = control["address"]
        if address in ambiguous:
            raise ValueError("target Pose address が曖昧です: {}".format(address))
        node = index.get(address)
        if node is None:
            skipped.append({"address": address, "reason": "target_missing"})
            continue
        for attribute in control["attributes"]:
            plug = "{}.{}".format(node, attribute["name"])
            if not cmds.objExists(plug) or cmds.getAttr(plug, lock=True) or not cmds.getAttr(plug, keyable=True):
                skipped.append({"address": address, "attribute": attribute["name"], "reason": "unavailable"})
                continue
            current_type = cmds.getAttr(plug, type=True)
            if current_type != attribute["type"]:
                skipped.append({"address": address, "attribute": attribute["name"], "reason": "type_mismatch"})
                continue
            incoming = cmds.listConnections(plug, source=True, destination=False, plugs=True) or []
            if incoming and not all(cmds.nodeType(source.split(".", 1)[0]).startswith("animCurve") for source in incoming):
                skipped.append({"address": address, "attribute": attribute["name"], "reason": "driven"})
                continue
            saved = attribute["value"]
            if current_type == "enum":
                value = _enum_index(plug, saved)
            else:
                value = _blended_value(cmds.getAttr(plug), saved, current_type, float(blend))
            operations.append((node, attribute["name"], plug, value, bool(incoming)))

    if operations:
        undo_utils.require_enabled("Pose Apply")
        cmds.undoInfo(openChunk=True, chunkName="YWTA Pose Apply")
        failed = False
        try:
            for node, attribute, plug, value, animated in operations:
                if animated:
                    cmds.setKeyframe(node, attribute=attribute, value=value)
                    cmds.dgdirty(plug)
                else:
                    cmds.setAttr(plug, value)
        except Exception:
            failed = True
            raise
        finally:
            cmds.undoInfo(closeChunk=True)
            if failed:
                cmds.undo()
    return {
        "applied": len(operations),
        "skipped": skipped,
        "unit_mismatches": unit_mismatches,
        "source_units": {key: data.get(key) for key in scene_units},
        "scene_units": scene_units,
    }


def save_selected():
    """選択コントロールをダイアログで保存する。"""
    selected = _long_nodes()
    paths = cmds.fileDialog2(fileMode=0, dialogStyle=2, caption="Save Pose", fileFilter="JSON (*.json)")
    if not paths:
        return None
    return save(selected, paths[0])


def save_temp_selected():
    """選択controlをMayaユーザー用の一時Pose JSONへ保存する。"""
    selected = _long_nodes()
    path = save_temp(selected)
    cmds.inViewMessage(
        statusMessage="Saved temporary pose.",
        position="topCenter",
        fade=True,
    )
    return path


def load_temp_with_settings():
    """保存済みBlend/Selected-only設定で一時Poseを適用する。"""
    blend, selected_only = get_load_settings()
    selected = _long_nodes() if selected_only else None
    result = load_temp(nodes=selected, blend=blend)
    if result["unit_mismatches"]:
        cmds.warning("Pose unit mismatch {}; raw値で適用しました。".format(", ".join(result["unit_mismatches"])))
    return result


def load_pose(selected_only=False, blend=1.0):
    """ダイアログで選んだポーズを scene または選択へ適用する。"""
    selected = _long_nodes() if selected_only else None
    paths = cmds.fileDialog2(fileMode=1, dialogStyle=2, caption="Load Pose", fileFilter="JSON (*.json)")
    if not paths:
        return None
    result = apply(read(paths[0]), nodes=selected, blend=blend)
    if result["unit_mismatches"]:
        cmds.warning("Pose unit mismatch {}; raw値で適用しました。".format(", ".join(result["unit_mismatches"])))
    return result


def load_pose_with_settings():
    """保存済みBlend/Selected-only設定でPoseファイルを適用する。"""
    blend, selected_only = get_load_settings()
    return load_pose(selected_only=selected_only, blend=blend)


def show_load_options():
    """PoseのBlendとSelected-onlyを設定して適用するUIを表示する。"""
    window = "ywtaPoseLoadOptionsWindow"
    if cmds.window(window, exists=True):
        cmds.deleteUI(window)
    blend, selected_only = get_load_settings()
    cmds.window(window, title="YWTA Load Pose", sizeable=False)
    cmds.columnLayout(adjustableColumn=True, rowSpacing=8, width=360)
    blend_field = cmds.floatSliderGrp(
        label="Blend",
        field=True,
        minValue=0.0,
        maxValue=1.0,
        fieldMinValue=0.0,
        fieldMaxValue=1.0,
        value=blend,
    )
    selected_field = cmds.checkBox(
        label="Apply to selected controls only",
        value=selected_only,
    )

    def apply_options(*_args):
        set_load_settings(
            cmds.floatSliderGrp(blend_field, query=True, value=True),
            cmds.checkBox(selected_field, query=True, value=True),
        )
        return load_pose_with_settings()

    cmds.button(label="Load Pose...", command=apply_options)
    cmds.showWindow(window)
    return window
