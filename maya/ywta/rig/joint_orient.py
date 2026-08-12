"""未リグjointを直接の子方向へ安全に静的orientする。"""

from __future__ import absolute_import

import math

import maya.cmds as cmds

from ywta.core import undo_utils
from ywta.rig import joint_insert


def _joints(nodes):
    """joint列をUUIDで重複排除したロングパスへ解決する。"""
    source = nodes if nodes is not None else cmds.ls(selection=True, long=True, type="joint")
    if isinstance(source, str):
        source = [source]
    if not source:
        raise ValueError("orientするjointを1つ以上選択してください。")
    result = []
    seen = set()
    for node in source:
        matches = cmds.ls(node, long=True, type="joint") or []
        if len(matches) != 1:
            raise ValueError("jointを一意に解決できません: {}".format(node))
        node_uuid = (cmds.ls(matches[0], uuid=True) or [None])[0]
        if node_uuid not in seen:
            seen.add(node_uuid)
            result.append(matches[0])
    return result


def _child(joint):
    """分岐のない直接の子jointを返す。"""
    children = cmds.listRelatives(joint, children=True, fullPath=True, type="joint") or []
    if len(children) != 1:
        raise ValueError("jointは直接の子jointを1つだけ持つ必要があります: {}".format(joint))
    return children[0]


def _validate_editable(joint, child):
    """orientが安全な未リグ親子かをscene編集前に検証する。"""
    referenced = [node for node in (joint, child) if cmds.referenceQuery(node, isNodeReferenced=True)]
    if referenced:
        raise ValueError("参照jointはorientできません: {}".format(", ".join(referenced)))
    dependencies = joint_insert.rig_dependencies((joint, child))
    if dependencies:
        raise ValueError("skin/constraint/IK接続済みjointはorientできません: {}".format(", ".join(dependencies)))
    blocked = []
    for node, compounds in ((joint, ("rotate", "jointOrient", "rotateAxis")), (child, ("translate", "rotate"))):
        for compound in compounds:
            for axis in "XYZ":
                plug = "{}.{}{}".format(node, compound, axis)
                if not cmds.getAttr(plug, settable=True):
                    blocked.append(plug)
    if blocked:
        raise ValueError("orientに必要なchannelが編集できません: {}".format(", ".join(blocked)))
    rotation = cmds.getAttr(joint + ".rotate")[0]
    if any(abs(float(value)) > 1.0e-8 for value in rotation):
        raise ValueError("joint.rotateを0にしてからorientしてください: {}".format(joint))
    start = cmds.xform(joint, query=True, worldSpace=True, translation=True)
    end = cmds.xform(child, query=True, worldSpace=True, translation=True)
    if math.sqrt(sum((end[index] - start[index]) ** 2 for index in range(3))) <= 1.0e-8:
        raise ValueError("親子jointが同一world位置です: {}".format(joint))


def orient_to_children(joints):
    """指定jointの+X軸を子へ向け、+Yをsecondary axisにする。"""
    joints = _joints(joints)
    plans = []
    for joint in joints:
        child = _child(joint)
        _validate_editable(joint, child)
        plans.append(joint)
    plans.sort(key=lambda node: node.count("|"), reverse=True)

    selection = cmds.ls(selection=True, long=True) or []
    undo_utils.require_enabled("Orient Joints to Children")
    cmds.undoInfo(openChunk=True, chunkName="YWTA Orient Joints to Children")
    failed = False
    try:
        for joint in plans:
            cmds.joint(
                joint,
                edit=True,
                orientJoint="xyz",
                secondaryAxisOrient="yup",
                children=False,
                zeroScaleOrient=True,
            )
        if selection:
            cmds.select(selection, replace=True)
        else:
            cmds.select(clear=True)
    except Exception:
        failed = True
        raise
    finally:
        cmds.undoInfo(closeChunk=True)
        if failed:
            cmds.undo()
    return plans


def orient_selected(include_descendants=True):
    """選択jointまたはその階層の非leaf jointを子方向へorientする。"""
    selected = _joints(None)
    if include_descendants:
        candidates = list(selected)
        for root in selected:
            candidates.extend(cmds.listRelatives(root, allDescendents=True, fullPath=True, type="joint") or [])
        candidates = _joints(candidates)
        selected = [joint for joint in candidates if cmds.listRelatives(joint, children=True, type="joint")]
        if not selected:
            raise ValueError("orientできる子joint付きjointが選択階層にありません。")
    return orient_to_children(selected)
