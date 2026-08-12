"""安全な versioned JSON で Maya joint hierarchy を保存・再構築する。"""

from __future__ import absolute_import

import json
import math
import os
import tempfile

import maya.cmds as cmds

from ywta.core import undo_utils


FORMAT = "ywta.skeleton"
VERSION = 2
SUPPORTED_VERSIONS = {1, VERSION}
TEMP_SKELETON_FILENAME = "ywta_temp_skeleton.json"
VECTOR_ATTRIBUTES = (
    "translate",
    "rotate",
    "scale",
    "jointOrient",
    "rotateAxis",
    "preferredAngle",
    "minRotLimit",
    "maxRotLimit",
)
BOOLEAN_VECTOR_ATTRIBUTES = (
    "minRotLimitEnable",
    "maxRotLimitEnable",
)
SCALAR_ATTRIBUTES = (
    "rotateOrder",
    "radius",
    "segmentScaleCompensate",
    "drawStyle",
    "visibility",
    "side",
    "type",
    "drawLabel",
)
STRING_ATTRIBUTES = ("otherType",)
MATRIX_ATTRIBUTES = ("offsetParentMatrix",)
ALL_ATTRIBUTES = VECTOR_ATTRIBUTES + BOOLEAN_VECTOR_ATTRIBUTES + SCALAR_ATTRIBUTES + STRING_ATTRIBUTES + MATRIX_ATTRIBUTES
CHANNEL_ATTRIBUTES = (
    "translateX",
    "translateY",
    "translateZ",
    "rotateX",
    "rotateY",
    "rotateZ",
    "scaleX",
    "scaleY",
    "scaleZ",
    "visibility",
)


def _joint_path(joint):
    """root joint を一意なロングパスへ解決する。"""
    matches = cmds.ls(joint, type="joint", long=True) or []
    if len(matches) != 1:
        raise ValueError("root joint を一意に解決できません: {}".format(joint))
    return matches[0]


def _portable_name(joint):
    """DAG path と namespace を除いた可搬名を返す。"""
    return joint.rsplit("|", 1)[-1].rsplit(":", 1)[-1]


def _attribute_value(joint, attribute):
    """Maya 属性値を JSON 配列または scalar へ正規化する。"""
    value = cmds.getAttr("{}.{}".format(joint, attribute))
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], tuple):
        return list(value[0])
    if isinstance(value, tuple):
        return list(value)
    return value


def capture(root):
    """joint hierarchy を親 index 付き辞書へ変換する。"""
    root = _joint_path(root)
    joints = []

    def visit(joint, parent_index):
        index = len(joints)
        attributes = {
            attribute: _attribute_value(joint, attribute)
            for attribute in ALL_ATTRIBUTES
            if cmds.objExists("{}.{}".format(joint, attribute))
        }
        channels = {
            attribute: {
                "locked": bool(cmds.getAttr("{}.{}".format(joint, attribute), lock=True)),
                "keyable": bool(cmds.getAttr("{}.{}".format(joint, attribute), keyable=True)),
                "channel_box": bool(cmds.getAttr("{}.{}".format(joint, attribute), channelBox=True)),
            }
            for attribute in CHANNEL_ATTRIBUTES
        }
        joints.append(
            {
                "name": _portable_name(joint),
                "parent": parent_index,
                "attributes": attributes,
                "channels": channels,
            }
        )
        children = cmds.listRelatives(joint, children=True, type="joint", fullPath=True) or []
        for child in children:
            visit(child, index)

    visit(root, None)
    return {
        "format": FORMAT,
        "version": VERSION,
        "scene": {
            "linear_unit": cmds.currentUnit(query=True, linear=True),
            "angle_unit": cmds.currentUnit(query=True, angle=True),
            "up_axis": cmds.upAxis(query=True, axis=True),
        },
        "joints": joints,
    }


def _finite_values(value, count, label):
    """固定長の有限数配列を検証する。"""
    if not isinstance(value, list) or len(value) != count:
        raise ValueError("{} は長さ{}の配列にしてください。".format(label, count))
    for item in value:
        if not isinstance(item, (int, float)) or isinstance(item, bool) or not math.isfinite(float(item)):
            raise ValueError("{} に不正な数値があります。".format(label))


def _validate(data):
    """外部 skeleton JSON を scene 編集前に完全検証する。"""
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError("YWTA Skeleton ファイルではありません。")
    if data.get("version") not in SUPPORTED_VERSIONS:
        raise ValueError("未対応の Skeleton version です: {}".format(data.get("version")))
    scene = data.get("scene")
    if scene is not None and (
        not isinstance(scene, dict)
        or set(scene) != {"linear_unit", "angle_unit", "up_axis"}
        or not isinstance(scene.get("linear_unit"), str)
        or not scene["linear_unit"]
        or not isinstance(scene.get("angle_unit"), str)
        or not scene["angle_unit"]
        or scene.get("up_axis") not in {"y", "z"}
    ):
        raise ValueError("scene conventionが不正です。")
    joints = data.get("joints")
    if not isinstance(joints, list) or not joints:
        raise ValueError("joints がありません。")
    sibling_names = set()
    for index, joint in enumerate(joints):
        if not isinstance(joint, dict):
            raise ValueError("joint {} が不正です。".format(index))
        name = joint.get("name")
        parent = joint.get("parent")
        if not isinstance(name, str) or not name or "|" in name or ":" in name:
            raise ValueError("joint {} の name が不正です。".format(index))
        if index == 0:
            if parent is not None:
                raise ValueError("root joint の parent は null にしてください。")
        elif not isinstance(parent, int) or isinstance(parent, bool) or parent < 0 or parent >= index:
            raise ValueError("joint {} の parent index が不正です。".format(index))
        sibling_key = (parent, name)
        if sibling_key in sibling_names:
            raise ValueError("同じ親に joint 名が重複しています: {}".format(name))
        sibling_names.add(sibling_key)

        attributes = joint.get("attributes")
        if not isinstance(attributes, dict):
            raise ValueError("joint {} の attributes が不正です。".format(index))
        unknown = set(attributes) - set(ALL_ATTRIBUTES)
        if unknown:
            raise ValueError("未対応の joint 属性です: {}".format(", ".join(sorted(unknown))))
        for attribute in VECTOR_ATTRIBUTES:
            if attribute in attributes:
                _finite_values(attributes[attribute], 3, "{}.{}".format(name, attribute))
        for attribute in BOOLEAN_VECTOR_ATTRIBUTES:
            if attribute in attributes:
                value = attributes[attribute]
                if not isinstance(value, list) or len(value) != 3 or any(not isinstance(item, bool) for item in value):
                    raise ValueError("{}.{}が不正です。".format(name, attribute))
        for attribute in MATRIX_ATTRIBUTES:
            if attribute in attributes:
                _finite_values(attributes[attribute], 16, "{}.{}".format(name, attribute))
        for attribute in SCALAR_ATTRIBUTES:
            if attribute not in attributes:
                continue
            value = attributes[attribute]
            if attribute in {"segmentScaleCompensate", "visibility", "drawLabel"}:
                valid = isinstance(value, bool)
            elif attribute in {"rotateOrder", "drawStyle", "side", "type"}:
                valid = isinstance(value, int) and not isinstance(value, bool)
            else:
                valid = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))
            if not valid:
                raise ValueError("{}.{} が不正です。".format(name, attribute))
        for attribute in STRING_ATTRIBUTES:
            if attribute in attributes and not isinstance(attributes[attribute], str):
                raise ValueError("{}.{}が不正です。".format(name, attribute))

        channels = joint.get("channels")
        if channels is not None:
            if not isinstance(channels, dict) or set(channels) - set(CHANNEL_ATTRIBUTES):
                raise ValueError("{}.channelsが不正です。".format(name))
            for attribute, state in channels.items():
                if not isinstance(state, dict) or set(state) != {"locked", "keyable", "channel_box"}:
                    raise ValueError("{}.channels.{}が不正です。".format(name, attribute))
                if any(not isinstance(state[key], bool) for key in state):
                    raise ValueError("{}.channels.{}が不正です。".format(name, attribute))
    return data


def save(root, file_path):
    """joint hierarchy を JSON へ原子的に保存する。"""
    data = capture(root)
    target = os.path.abspath(file_path)
    directory = os.path.dirname(target)
    if not os.path.isdir(directory):
        raise ValueError("保存先ディレクトリがありません: {}".format(directory))
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=directory,
        prefix=".ywta_skeleton_",
        suffix=".tmp",
        delete=False,
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
    """Skeleton JSON を読み込み、検証済み辞書を返す。"""
    with open(file_path, "r", encoding="utf-8") as handle:
        return _validate(json.load(handle))


def _namespace_prefix(namespace):
    """入力 namespace を Maya の絶対でない prefix へ正規化する。"""
    namespace = (namespace or "").strip().strip(":")
    return namespace + ":" if namespace else ""


def _ensure_namespace(namespace):
    """入れ子 namespace を root から順に作成する。"""
    namespace = (namespace or "").strip().strip(":")
    if not namespace:
        return
    parent = ":"
    full_name = ""
    for segment in namespace.split(":"):
        full_name = segment if not full_name else full_name + ":" + segment
        if not cmds.namespace(exists=":" + full_name):
            cmds.namespace(add=segment, parent=parent)
        parent = ":" + full_name


def _set_attributes(joint, attributes):
    """検証済み joint 属性を適切な Maya 型で設定する。"""
    for attribute in MATRIX_ATTRIBUTES:
        if attribute in attributes:
            cmds.setAttr("{}.{}".format(joint, attribute), *attributes[attribute], type="matrix")
    for attribute in VECTOR_ATTRIBUTES:
        if attribute in attributes:
            cmds.setAttr("{}.{}".format(joint, attribute), *attributes[attribute])
    for attribute in BOOLEAN_VECTOR_ATTRIBUTES:
        if attribute in attributes:
            cmds.setAttr("{}.{}".format(joint, attribute), *attributes[attribute])
    for attribute in SCALAR_ATTRIBUTES:
        if attribute in attributes:
            cmds.setAttr("{}.{}".format(joint, attribute), attributes[attribute])
    for attribute in STRING_ATTRIBUTES:
        if attribute in attributes:
            cmds.setAttr(
                "{}.{}".format(joint, attribute),
                attributes[attribute],
                type="string",
            )


def _set_channel_states(joint, states):
    """bake後に検証済みchannel表示・lock状態を復元する。"""
    for attribute, state in (states or {}).items():
        plug = "{}.{}".format(joint, attribute)
        cmds.setAttr(plug, lock=False)
        cmds.setAttr(
            plug,
            keyable=state["keyable"],
            channelBox=state["channel_box"],
        )
        cmds.setAttr(plug, lock=state["locked"])


def _scene_convention_mismatches(data):
    """保存元と現在sceneで異なるunit/up axis名を返す。"""
    saved = data.get("scene")
    if saved is None:
        return []
    current = {
        "linear_unit": cmds.currentUnit(query=True, linear=True),
        "angle_unit": cmds.currentUnit(query=True, angle=True),
        "up_axis": cmds.upAxis(query=True, axis=True),
    }
    return [key for key in current if saved[key] != current[key]]


def create(
    data,
    namespace="",
    allow_scene_mismatch=False,
    bake_to_joint_orient=False,
    zero_joint_scales=False,
):
    """検証済み hierarchy を衝突拒否・一括 Undo で作成する。"""
    data = _validate(data)
    if not isinstance(allow_scene_mismatch, bool):
        raise ValueError("allow_scene_mismatchはboolにしてください。")
    if not isinstance(bake_to_joint_orient, bool):
        raise ValueError("bake_to_joint_orientはboolにしてください。")
    if not isinstance(zero_joint_scales, bool):
        raise ValueError("zero_joint_scalesはboolにしてください。")
    mismatches = _scene_convention_mismatches(data)
    if mismatches and not allow_scene_mismatch:
        raise ValueError("Skeleton scene conventionが一致しません: {}".format(", ".join(mismatches)))
    prefix = _namespace_prefix(namespace)
    root_name = prefix + data["joints"][0]["name"]
    if cmds.objExists(":" + root_name):
        raise ValueError("import 先 root が既に存在します: {}".format(root_name))

    undo_utils.require_enabled("Skeleton Import")
    cmds.undoInfo(openChunk=True, chunkName="YWTA Skeleton Import")
    failed = False
    created = []
    try:
        _ensure_namespace(namespace)
        for item in data["joints"]:
            parent = created[item["parent"]] if item["parent"] is not None else None
            name = prefix + item["name"]
            kwargs = {"name": ":" + name}
            if parent:
                kwargs["parent"] = parent
            joint = cmds.createNode("joint", **kwargs)
            expected_leaf = name
            if joint.rsplit("|", 1)[-1] != expected_leaf:
                raise RuntimeError("joint 名が競合しています: {} -> {}".format(name, joint))
            _set_attributes(joint, item["attributes"])
            created.append((cmds.ls(joint, long=True) or [joint])[0])
        if zero_joint_scales:
            for joint in created:
                cmds.makeIdentity(
                    joint,
                    apply=True,
                    translate=False,
                    rotate=False,
                    scale=True,
                )
        if bake_to_joint_orient:
            for joint in created:
                cmds.makeIdentity(
                    joint,
                    apply=True,
                    translate=False,
                    rotate=True,
                    scale=False,
                )
        for joint, item in zip(created, data["joints"]):
            _set_channel_states(joint, item.get("channels"))
        cmds.select(created[0], replace=True)
    except Exception:
        failed = True
        raise
    finally:
        cmds.undoInfo(closeChunk=True)
        if failed:
            cmds.undo()
    return created


def load(
    file_path,
    namespace="",
    allow_scene_mismatch=False,
    bake_to_joint_orient=False,
    zero_joint_scales=False,
):
    """Skeleton JSON を読み込み scene に作成する。"""
    return create(
        read(file_path),
        namespace=namespace,
        allow_scene_mismatch=allow_scene_mismatch,
        bake_to_joint_orient=bake_to_joint_orient,
        zero_joint_scales=zero_joint_scales,
    )


def temp_skeleton_path():
    """Mayaユーザー用の一時Skeleton JSONパスを返す。"""
    return os.path.join(cmds.internalVar(userAppDir=True), TEMP_SKELETON_FILENAME)


def save_temp(root, file_path=None):
    """root hierarchyを固定または指定の一時JSONへ保存する。"""
    return save(root, file_path or temp_skeleton_path())


def hierarchy_root(joint):
    """選択jointからjoint parentだけを辿ったhierarchy rootを返す。"""
    matches = cmds.ls(joint, type="joint", long=True) or []
    if len(matches) != 1:
        raise ValueError("jointを一意に解決できません: {}".format(joint))
    root = matches[0]
    while True:
        parents = cmds.listRelatives(root, parent=True, type="joint", fullPath=True) or []
        if not parents:
            return root
        root = parents[0]


def load_temp(
    file_path=None,
    namespace="",
    allow_scene_mismatch=False,
    bake_to_joint_orient=False,
    zero_joint_scales=False,
):
    """一時Skeleton JSONを既存の検証済みimport経路で再構築する。"""
    return load(
        file_path or temp_skeleton_path(),
        namespace=namespace,
        allow_scene_mismatch=allow_scene_mismatch,
        bake_to_joint_orient=bake_to_joint_orient,
        zero_joint_scales=zero_joint_scales,
    )


def save_selected():
    """選択 root joint をファイルダイアログで保存する。"""
    selected = cmds.ls(selection=True, type="joint", long=True) or []
    if len(selected) != 1:
        raise ValueError("保存する root joint を1つ選択してください。")
    paths = cmds.fileDialog2(
        fileMode=0,
        dialogStyle=2,
        caption="Export Skeleton",
        fileFilter="YWTA Skeleton (*.skeleton.json)",
    )
    if not paths:
        return None
    return save(selected[0], paths[0])


def save_temp_selected():
    """選択jointのhierarchy rootをMayaユーザー用の一時JSONへ保存する。"""
    selected = cmds.ls(selection=True, type="joint", long=True) or []
    if len(selected) != 1:
        raise ValueError("一時保存するjointを1つ選択してください。")
    path = save_temp(hierarchy_root(selected[0]))
    cmds.inViewMessage(
        statusMessage="Saved temporary skeleton.",
        position="topCenter",
        fade=True,
    )
    return path


def load_temp_dialog(
    bake_to_joint_orient=False,
    zero_joint_scales=False,
):
    """任意namespaceを指定して一時Skeleton JSONをimportする。"""
    result = cmds.promptDialog(
        title="Import Temporary Skeleton",
        message="Namespace (optional):",
        button=["Import", "Cancel"],
        defaultButton="Import",
        cancelButton="Cancel",
        dismissString="Cancel",
    )
    if result != "Import":
        return None
    return load_temp(
        namespace=cmds.promptDialog(query=True, text=True),
        bake_to_joint_orient=bake_to_joint_orient,
        zero_joint_scales=zero_joint_scales,
    )


def load_dialog(bake_to_joint_orient=False, zero_joint_scales=False):
    """ファイルと任意 namespace をダイアログで指定して import する。"""
    paths = cmds.fileDialog2(
        fileMode=1,
        dialogStyle=2,
        caption="Import Skeleton",
        fileFilter="YWTA Skeleton (*.skeleton.json)",
    )
    if not paths:
        return None
    result = cmds.promptDialog(
        title="Import Skeleton",
        message="Namespace (optional):",
        button=["Import", "Cancel"],
        defaultButton="Import",
        cancelButton="Cancel",
        dismissString="Cancel",
    )
    if result != "Import":
        return None
    namespace = cmds.promptDialog(query=True, text=True)
    return load(
        paths[0],
        namespace=namespace,
        bake_to_joint_orient=bake_to_joint_orient,
        zero_joint_scales=zero_joint_scales,
    )
