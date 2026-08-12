"""namespace を跨いで利用できる Maya ポーズ JSON の保存・適用。"""

from __future__ import absolute_import

import json
import math
import os
import tempfile

import maya.cmds as cmds


FORMAT = "ywta.pose"
VERSION = 1
POSE_ID_ATTRIBUTE = "ywtaPoseId"
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


def _long_nodes(nodes=None):
    """対象ノードを順序保持したロングパスへ解決する。"""
    values = cmds.ls(nodes, long=True) if nodes is not None else cmds.ls(selection=True, long=True)
    if not values:
        raise ValueError("ポーズ対象のコントロールを選択してください。")
    result = []
    seen = set()
    for node in values:
        node_uuid = (cmds.ls(node, uuid=True) or [None])[0]
        if node_uuid and node_uuid not in seen:
            seen.add(node_uuid)
            result.append(node)
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
            return "id:" + value.strip()
    return "name:" + _base_name(node)


def set_pose_id(node, pose_id):
    """コントロールへ rig 間で安定した Pose ID を設定する。"""
    if not pose_id or not pose_id.strip():
        raise ValueError("Pose ID が空です。")
    matches = cmds.ls(node, long=True) or []
    if len(matches) != 1:
        raise ValueError("ノードを一意に解決できません: {}".format(node))
    plug = "{}.{}".format(matches[0], POSE_ID_ATTRIBUTE)
    if not cmds.objExists(plug):
        cmds.addAttr(matches[0], longName=POSE_ID_ATTRIBUTE, dataType="string")
    cmds.setAttr(plug, pose_id.strip(), type="string")
    return plug


def _capture_attribute(node, attribute):
    """対応する keyable scalar 属性を JSON 値へ変換する。"""
    plug = "{}.{}".format(node, attribute)
    if cmds.getAttr(plug, lock=True):
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
    return {"format": FORMAT, "version": VERSION, "controls": controls}


def _validate(data):
    """外部 JSON を scene 編集前に完全検証する。"""
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError("YWTA Pose ファイルではありません。")
    if data.get("version") != VERSION:
        raise ValueError("未対応の Pose version です: {}".format(data.get("version")))
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
            if not cmds.objExists(plug) or cmds.getAttr(plug, lock=True):
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
    return {"applied": len(operations), "skipped": skipped}


def save_selected():
    """選択コントロールをダイアログで保存する。"""
    selected = _long_nodes()
    paths = cmds.fileDialog2(fileMode=0, dialogStyle=2, caption="Save Pose", fileFilter="JSON (*.json)")
    if not paths:
        return None
    return save(selected, paths[0])


def load_pose(selected_only=False, blend=1.0):
    """ダイアログで選んだポーズを scene または選択へ適用する。"""
    selected = _long_nodes() if selected_only else None
    paths = cmds.fileDialog2(fileMode=1, dialogStyle=2, caption="Load Pose", fileFilter="JSON (*.json)")
    if not paths:
        return None
    return apply(read(paths[0]), nodes=selected, blend=blend)
