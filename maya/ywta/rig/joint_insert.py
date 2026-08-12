"""隣接する未リグ親子joint間へjointを安全に挿入する。"""

from __future__ import absolute_import

import re

import maya.cmds as cmds

from ywta.core import undo_utils


def _joint(node):
    """jointを一意なロングパスへ解決する。"""
    matches = cmds.ls(node, long=True, type="joint") or []
    if len(matches) != 1:
        raise ValueError("jointを一意に解決できません: {}".format(node))
    return matches[0]


def _leaf_name(node):
    """jointのnamespace付きleaf名を返す。"""
    return node.rsplit("|", 1)[-1]


def _absolute_name(name):
    """namespace付きnameをcurrent namespace非依存の絶対名へする。"""
    return ":" + name if ":" in name and not name.startswith(":") else name


def _resolve_uuid(node_uuid):
    """UUIDから現在のjointロングパスを返す。"""
    matches = cmds.ls(node_uuid, long=True, type="joint") or []
    if len(matches) != 1:
        raise RuntimeError("挿入中にjointを見失いました: {}".format(node_uuid))
    return matches[0]


def _planned_names(parent, count, pattern):
    """namespaceを継承した挿入joint名を作る。"""
    if not isinstance(pattern, str) or not pattern.strip() or "|" in pattern or ":" in pattern:
        raise ValueError("name patternはnamespaceを含まない短名にしてください。")
    match = re.search(r"#+", pattern)
    if match is None:
        raise ValueError("name patternには#を1つ以上含めてください。")
    namespace, separator, _base = _leaf_name(parent).rpartition(":")
    prefix = namespace + separator if separator else ""
    width = len(match.group(0))
    names = []
    for index in range(1, count + 1):
        leaf = pattern[: match.start()] + str(index).zfill(width) + pattern[match.end() :]
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", leaf) is None:
            raise ValueError("挿入joint名は英数字とunderscoreだけにしてください: {}".format(leaf))
        names.append(prefix + leaf)
    if len(set(names)) != len(names):
        raise ValueError("挿入joint名が重複しています。")
    conflicts = [name for name in names if cmds.objExists(_absolute_name(name))]
    if conflicts:
        raise ValueError("挿入joint名がsceneに既にあります: {}".format(", ".join(conflicts)))
    return names


def rig_dependencies(joints):
    """階層変更を拒否するskin / constraint / IK依存を返す。"""
    joint_ids = {(cmds.ls(joint, uuid=True) or [None])[0] for joint in joints}
    reasons = []
    for cluster in cmds.ls(type="skinCluster") or []:
        influences = cmds.skinCluster(cluster, query=True, influence=True) or []
        influence_ids = {(cmds.ls(influence, uuid=True) or [None])[0] for influence in influences}
        if not joint_ids.isdisjoint(influence_ids):
            reasons.append("skinCluster {}".format(cluster))
    for joint in joints:
        constraints = cmds.listConnections(joint, source=True, destination=True, type="constraint") or []
        reasons.extend("constraint {}".format(node) for node in constraints)
    for handle in cmds.ls(type="ikHandle") or []:
        chain = cmds.ikHandle(handle, query=True, jointList=True) or []
        chain_ids = {(cmds.ls(joint, uuid=True) or [None])[0] for joint in chain}
        if not joint_ids.isdisjoint(chain_ids):
            reasons.append("ikHandle {}".format(handle))
    return sorted(set(reasons))


def insert_joints(parent, child, count=1, name_pattern="insert_##_jnt"):
    """隣接親子joint間へ指定数を均等挿入する。

    Args:
        parent: 挿入区間の親joint。
        child: 挿入区間の子joint。
        count: 挿入数。1以上99以下。
        name_pattern: 連番用#を含むnamespaceなし短名。

    Returns:
        親から子の順に並んだ作成jointのロングパス。
    """
    if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 99:
        raise ValueError("挿入joint数は1以上99以下の整数にしてください。")
    parent = _joint(parent)
    child = _joint(child)
    children = cmds.listRelatives(parent, children=True, fullPath=True, type="joint") or []
    if children != [child]:
        raise ValueError("分岐のない直接の親子jointを指定してください。")
    referenced = [joint for joint in (parent, child) if cmds.referenceQuery(joint, isNodeReferenced=True)]
    if referenced:
        raise ValueError("参照jointには挿入できません: {}".format(", ".join(referenced)))
    dependencies = rig_dependencies((parent, child))
    if dependencies:
        raise ValueError("skin/constraint/IK接続済みjointには挿入できません: {}".format(", ".join(dependencies)))
    names = _planned_names(parent, count, name_pattern)
    start = cmds.xform(parent, query=True, worldSpace=True, translation=True)
    end = cmds.xform(child, query=True, worldSpace=True, translation=True)
    child_matrix = cmds.xform(child, query=True, worldSpace=True, matrix=True)
    child_uuid = (cmds.ls(child, uuid=True) or [None])[0]
    if child_uuid is None:
        raise RuntimeError("子jointのUUIDを取得できません: {}".format(child))

    undo_utils.require_enabled("Insert Joints")
    cmds.undoInfo(openChunk=True, chunkName="YWTA Insert Joints")
    failed = False
    try:
        created = []
        current_parent = parent
        for index, name in enumerate(names, start=1):
            inserted = cmds.insertJoint(current_parent)
            inserted = cmds.rename(inserted, _absolute_name(name))
            if _leaf_name(inserted) != name:
                raise RuntimeError("挿入joint名がMayaに変更されました: {}".format(inserted))
            fraction = float(index) / float(count + 1)
            position = [start[axis] + (end[axis] - start[axis]) * fraction for axis in range(3)]
            cmds.xform(inserted, worldSpace=True, translation=position)
            inserted = (cmds.ls(inserted, long=True, type="joint") or [inserted])[0]
            created.append(inserted)
            current_parent = inserted
        cmds.xform(_resolve_uuid(child_uuid), worldSpace=True, matrix=child_matrix)
        created = [_joint(_absolute_name(name)) for name in names]
        cmds.select(created, replace=True)
    except Exception:
        failed = True
        raise
    finally:
        cmds.undoInfo(closeChunk=True)
        if failed:
            cmds.undo()
    return created


def insert_selected(count=1, name_pattern="insert_##_jnt"):
    """選択した隣接2 jointから親子を判定してjointを挿入する。"""
    selected = cmds.ls(selection=True, long=True, type="joint") or []
    if len(selected) != 2:
        raise ValueError("隣接するjointを2つ選択してください。")
    first_parent = cmds.listRelatives(selected[0], parent=True, fullPath=True, type="joint") or []
    second_parent = cmds.listRelatives(selected[1], parent=True, fullPath=True, type="joint") or []
    if second_parent == [selected[0]]:
        parent, child = selected
    elif first_parent == [selected[1]]:
        child, parent = selected
    else:
        raise ValueError("選択jointは直接の親子ではありません。")
    return insert_joints(parent, child, count=count, name_pattern=name_pattern)


def show_options():
    """挿入数と名前を指定する小さなMaya UIを表示する。"""
    window = "ywtaInsertJointsWindow"
    if cmds.window(window, exists=True):
        cmds.deleteUI(window)
    cmds.window(window, title="YWTA Insert Joints", sizeable=False)
    cmds.columnLayout(adjustableColumn=True, rowSpacing=8, width=320)
    count_field = cmds.intSliderGrp(label="Count", field=True, minValue=1, maxValue=99, value=1)
    name_field = cmds.textFieldGrp(label="Name", text="insert_##_jnt")

    def run(*_args):
        return insert_selected(
            count=cmds.intSliderGrp(count_field, query=True, value=True),
            name_pattern=cmds.textFieldGrp(name_field, query=True, text=True),
        )

    cmds.button(label="Insert Between Selected", command=run)
    cmds.showWindow(window)
    return window
