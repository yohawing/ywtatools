"""rig階層とskinClusterを往復する選択ナビゲーション。"""

from __future__ import absolute_import

import maya.api.OpenMayaAnim as oma
import maya.cmds as cmds

from ywta.deform import skin_io


def _unique_nodes(nodes, node_type=None):
    """node列をUUIDで重複排除したロング名へ解決する。"""
    source = nodes if nodes is not None else cmds.ls(selection=True, long=True, objectsOnly=True)
    if not source:
        raise ValueError("選択対象を1つ以上指定してください。")
    result = []
    seen = set()
    for node in source:
        matches = cmds.ls(node, long=True, type=node_type) if node_type else cmds.ls(node, long=True)
        matches = matches or []
        if len(matches) != 1:
            raise ValueError("nodeを一意に解決できません: {}".format(node))
        node_uuid = (cmds.ls(matches[0], uuid=True) or [None])[0]
        if node_uuid not in seen:
            seen.add(node_uuid)
            result.append(matches[0])
    return result


def _select(nodes):
    """検証済みnode列を選択し、そのまま返す。"""
    if nodes:
        cmds.select(nodes, replace=True)
    else:
        cmds.select(clear=True)
    return nodes


def select_child_joints(roots=None):
    """選択階層の子孫jointを親から子の順で選択する。"""
    roots = _unique_nodes(roots)
    result = []
    seen = set()
    for root in roots:
        descendants = cmds.listRelatives(root, allDescendents=True, fullPath=True, type="joint") or []
        for joint in reversed(descendants):
            node_uuid = (cmds.ls(joint, uuid=True) or [None])[0]
            if node_uuid not in seen:
                seen.add(node_uuid)
                result.append(joint)
    return _select(result)


def select_child_meshes(roots=None):
    """選択階層直下の表示mesh transformを選択する。"""
    roots = _unique_nodes(roots)
    result = []
    seen = set()
    for root in roots:
        shapes = cmds.listRelatives(root, allDescendents=True, fullPath=True, type="mesh") or []
        for shape in reversed(shapes):
            if cmds.getAttr(shape + ".intermediateObject"):
                continue
            transform = (cmds.listRelatives(shape, parent=True, fullPath=True) or [None])[0]
            node_uuid = (cmds.ls(transform, uuid=True) or [None])[0]
            if transform and node_uuid not in seen:
                seen.add(node_uuid)
                result.append(transform)
    return _select(result)


def select_influencing_joints(meshes=None):
    """選択meshのskinClusterへ登録された全jointを選択する。"""
    source = meshes if meshes is not None else cmds.ls(selection=True, long=True, objectsOnly=True)
    if not source:
        raise ValueError("skinned meshを1つ以上選択してください。")
    result = []
    seen = set()
    for mesh in source:
        shape = skin_io._mesh_shape(mesh)
        cluster = skin_io._skin_cluster(shape)
        if cluster is None:
            raise ValueError("skinClusterが見つかりません: {}".format(shape))
        fn_skin = oma.MFnSkinCluster(skin_io._depend_node(cluster))
        for path in fn_skin.influenceObjects():
            joint = path.fullPathName()
            node_uuid = (cmds.ls(joint, uuid=True) or [None])[0]
            if node_uuid not in seen:
                seen.add(node_uuid)
                result.append(joint)
    return _select(result)


def select_influenced_meshes(joints=None):
    """選択jointがinfluenceとして登録された表示meshを選択する。"""
    joints = _unique_nodes(joints, node_type="joint")
    requested = {(cmds.ls(joint, uuid=True) or [None])[0] for joint in joints}
    result = []
    seen = set()
    for cluster in cmds.ls(type="skinCluster") or []:
        fn_skin = oma.MFnSkinCluster(skin_io._depend_node(cluster))
        influence_ids = {
            (cmds.ls(path.fullPathName(), uuid=True) or [None])[0]
            for path in fn_skin.influenceObjects()
        }
        if requested.isdisjoint(influence_ids):
            continue
        for geometry in cmds.skinCluster(cluster, query=True, geometry=True) or []:
            shapes = cmds.ls(geometry, long=True, type="mesh") or []
            if len(shapes) != 1 or cmds.getAttr(shapes[0] + ".intermediateObject"):
                continue
            transform = (cmds.listRelatives(shapes[0], parent=True, fullPath=True) or [None])[0]
            node_uuid = (cmds.ls(transform, uuid=True) or [None])[0]
            if transform and node_uuid not in seen:
                seen.add(node_uuid)
                result.append(transform)
    return _select(result)
