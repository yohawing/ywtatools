"""joint hierarchyを検証済みの名前へ安全に複製する。"""

from __future__ import absolute_import

import re
import uuid

import maya.cmds as cmds

from ywta.core import undo_utils


def _joint(node):
    """jointを一意なロングパスへ解決する。"""
    matches = cmds.ls(node, long=True, type="joint") or []
    if len(matches) != 1:
        raise ValueError("jointを一意に解決できません: {}".format(node))
    return matches[0]


def _hierarchy(root):
    """root以下のjointを親優先順で返す。"""
    result = []

    def visit(joint):
        result.append(joint)
        for child in cmds.listRelatives(joint, children=True, fullPath=True, type="joint") or []:
            visit(child)

    visit(root)
    return result


def _absolute_name(name):
    """current namespaceに依存しない絶対名を返す。"""
    return ":" + name.lstrip(":")


def _temporary_name(target):
    """targetと同じnamespaceに一意な一時名を作る。"""
    namespace, separator, _base = target.rpartition(":")
    prefix = namespace + separator if separator else ""
    return _absolute_name(prefix + "__ywta_joint_duplicate_{}".format(uuid.uuid4().hex))


def _resolve_uuid(node_uuid):
    """UUIDから一意なjointロングパスを返す。"""
    matches = cmds.ls(node_uuid, long=True, type="joint") or []
    if len(matches) != 1:
        raise RuntimeError("複製jointを見失いました: {}".format(node_uuid))
    return matches[0]


def plan(root, search, replacement):
    """sceneを変更せずjoint階層と複製後の予定名を検証する。"""
    if not isinstance(search, str) or not search:
        raise ValueError("Find文字列を指定してください。")
    if not isinstance(replacement, str) or "|" in replacement or ":" in replacement:
        raise ValueError("Replace文字列に'|' / ':'は使用できません。")
    root = _joint(root)
    descendants = cmds.listRelatives(root, allDescendents=True, fullPath=True) or []
    invalid = [node for node in descendants if cmds.nodeType(node) != "joint"]
    if invalid:
        raise ValueError("joint以外の子DAG nodeを含む階層は複製できません: {}".format(", ".join(invalid)))
    sources = _hierarchy(root)
    referenced = [node for node in sources if cmds.referenceQuery(node, isNodeReferenced=True)]
    parents = cmds.listRelatives(root, parent=True, fullPath=True) or []
    if parents and cmds.referenceQuery(parents[0], isNodeReferenced=True):
        referenced.append(parents[0])
    if referenced:
        raise ValueError("参照階層のjointは複製できません: {}".format(", ".join(referenced)))

    targets = []
    unchanged = []
    for source in sources:
        leaf = source.rsplit("|", 1)[-1]
        namespace, separator, base = leaf.rpartition(":")
        changed = base.replace(search, replacement)
        if changed == base:
            unchanged.append(leaf)
        if not changed:
            raise ValueError("複製後のjoint名が空です: {}".format(leaf))
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", changed) is None:
            raise ValueError("複製後のjoint名は英数字とunderscoreだけにしてください: {}".format(changed))
        targets.append(namespace + separator + changed if separator else changed)
    if unchanged:
        raise ValueError("Find文字列を含まないjointがあります: {}".format(", ".join(unchanged)))
    if len(set(targets)) != len(targets):
        raise ValueError("複製後のjoint名が階層内で重複します。")
    conflicts = [target for target in targets if cmds.ls(_absolute_name(target), long=True)]
    if conflicts:
        raise ValueError("複製後のjoint名がsceneに存在します: {}".format(", ".join(conflicts)))
    return {"root": root, "sources": sources, "targets": targets}


def duplicate_hierarchy(root, search, replacement):
    """joint hierarchyをFind/Replace名で複製し、単一Undoにする。"""
    duplicate_plan = plan(root, search, replacement)
    undo_utils.require_enabled("Duplicate Joint Hierarchy")
    cmds.undoInfo(openChunk=True, chunkName="YWTA Duplicate Joint Hierarchy")
    failed = False
    try:
        duplicate_root = cmds.duplicate(
            duplicate_plan["root"],
            renameChildren=True,
            returnRootsOnly=True,
        )[0]
        created = _hierarchy(_joint(duplicate_root))
        if len(created) != len(duplicate_plan["sources"]):
            raise RuntimeError("複製後のjoint数が一致しません。")
        records = []
        for node, target in zip(created, duplicate_plan["targets"]):
            node_uuid = (cmds.ls(node, uuid=True) or [None])[0]
            if node_uuid is None:
                raise RuntimeError("複製jointのUUIDを取得できません: {}".format(node))
            records.append((node_uuid, target))
        for node_uuid, target in records:
            cmds.rename(_resolve_uuid(node_uuid), _temporary_name(target))
        for node_uuid, target in records:
            renamed = cmds.rename(_resolve_uuid(node_uuid), _absolute_name(target))
            if renamed.rsplit("|", 1)[-1] != target:
                raise RuntimeError("複製joint名がMayaに変更されました: {}".format(renamed))
        result = [_resolve_uuid(node_uuid) for node_uuid, _target in records]
        cmds.select(result[0], replace=True)
    except Exception:
        failed = True
        raise
    finally:
        cmds.undoInfo(closeChunk=True)
        if failed:
            cmds.undo()
    return result


def duplicate_selected(search, replacement):
    """選択root joint階層をFind/Replace名で複製する。"""
    selected = cmds.ls(selection=True, long=True, type="joint") or []
    if len(selected) != 1:
        raise ValueError("複製するroot jointを1つ選択してください。")
    return duplicate_hierarchy(selected[0], search, replacement)


def show_options():
    """Find/Replaceを指定する小さなMaya UIを表示する。"""
    window = "ywtaDuplicateJointHierarchyWindow"
    if cmds.window(window, exists=True):
        cmds.deleteUI(window)
    cmds.window(window, title="YWTA Duplicate Joint Hierarchy", sizeable=False)
    cmds.columnLayout(adjustableColumn=True, rowSpacing=8, width=340)
    find_field = cmds.textFieldGrp(label="Find", text="L_")
    replace_field = cmds.textFieldGrp(label="Replace", text="R_")

    def run(*_args):
        return duplicate_selected(
            cmds.textFieldGrp(find_field, query=True, text=True),
            cmds.textFieldGrp(replace_field, query=True, text=True),
        )

    cmds.button(label="Duplicate Selected Hierarchy", command=run)
    cmds.showWindow(window)
    return window
