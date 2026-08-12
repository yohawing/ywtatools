"""名前と衝突を事前検証する静的joint hierarchy mirror。"""

from __future__ import absolute_import

import re
import uuid

import maya.cmds as cmds


_SIDE_TOKEN = re.compile(r"(^|_)(left|right|lf|rt|l|r)(?=_|$)", re.IGNORECASE)
_SIDE_PAIRS = {
    "left": "right",
    "right": "left",
    "lf": "rt",
    "rt": "lf",
    "l": "r",
    "r": "l",
}


def _styled_token(source, target):
    """source tokenの大文字小文字形式をtargetへ反映する。"""
    if source.isupper():
        return target.upper()
    if source[:1].isupper():
        return target.title()
    return target


def mirrored_name(joint):
    """joint leafの最初のside tokenを反対側へ置換する。"""
    leaf = joint.rsplit("|", 1)[-1]
    namespace, separator, name = leaf.rpartition(":")
    match = _SIDE_TOKEN.search(name)
    if match is None:
        raise ValueError("side tokenがありません: {}".format(leaf))
    source = match.group(2)
    target = _styled_token(source, _SIDE_PAIRS[source.lower()])
    mirrored = name[: match.start(2)] + target + name[match.end(2) :]
    return namespace + separator + mirrored if separator else mirrored


def _joint_path(joint):
    """jointを一意なロングパスへ解決する。"""
    matches = cmds.ls(joint, long=True, type="joint") or []
    if len(matches) != 1:
        raise ValueError("jointを一意に解決できません: {}".format(joint))
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


def plan(root):
    """sceneを変更せずmirror元と予定名を完全検証する。"""
    root = _joint_path(root)
    sources = _hierarchy(root)
    targets = [mirrored_name(source) for source in sources]
    if len(set(targets)) != len(targets):
        raise ValueError("mirror後のjoint名が階層内で重複します。")
    for target in targets:
        if cmds.ls(target, long=True):
            raise ValueError("mirror先jointが既に存在します: {}".format(target))
    parents = cmds.listRelatives(root, parent=True, fullPath=True, type="joint") or []
    target_parent = None
    if parents:
        parent_name = mirrored_name(parents[0])
        matches = cmds.ls(parent_name, long=True, type="joint") or []
        if len(matches) != 1:
            raise ValueError("mirror先parent jointを一意に解決できません: {}".format(parent_name))
        target_parent = matches[0]
    return {
        "root": root,
        "sources": sources,
        "targets": targets,
        "target_parent": target_parent,
    }


def _resolve_uuid(node_uuid):
    """UUIDから一意なロングパスを返す。"""
    matches = cmds.ls(node_uuid, long=True) or []
    if len(matches) != 1:
        raise RuntimeError("mirror joint UUIDを解決できません: {}".format(node_uuid))
    return matches[0]


def mirror_hierarchy(root):
    """joint hierarchyをworld YZ面で静的mirrorし、単一Undoにする。"""
    mirror_plan = plan(root)
    cmds.undoInfo(openChunk=True, chunkName="YWTA Mirror Joint Hierarchy")
    failed = False
    try:
        created = cmds.mirrorJoint(
            mirror_plan["root"],
            mirrorYZ=True,
            mirrorBehavior=True,
        ) or []
        if len(created) != len(mirror_plan["sources"]):
            raise RuntimeError("mirror後のjoint数が一致しません。")
        records = []
        for node, target in zip(created, mirror_plan["targets"]):
            node_uuid = (cmds.ls(node, uuid=True) or [None])[0]
            if node_uuid is None:
                raise RuntimeError("作成jointのUUIDを取得できません: {}".format(node))
            records.append((node_uuid, target))
        for node_uuid, _target in records:
            cmds.rename(
                _resolve_uuid(node_uuid),
                "__ywta_joint_mirror_{}".format(uuid.uuid4().hex),
            )
        for node_uuid, target in records:
            renamed = cmds.rename(_resolve_uuid(node_uuid), target)
            if renamed.rsplit("|", 1)[-1] != target:
                raise RuntimeError("mirror joint名が競合しました: {}".format(target))
        if mirror_plan["target_parent"]:
            cmds.parent(
                _resolve_uuid(records[0][0]),
                mirror_plan["target_parent"],
            )
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


def mirror_selected_hierarchy():
    """選択root joint hierarchyをworld YZ面でmirrorする。"""
    selected = cmds.ls(selection=True, long=True, type="joint") or []
    if len(selected) != 1:
        raise ValueError("mirrorするroot jointを1つ選択してください。")
    return mirror_hierarchy(selected[0])
