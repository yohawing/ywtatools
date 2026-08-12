"""選択したskinCluster influenceをウェイト非破壊で追加・削除する。"""

from __future__ import absolute_import

import maya.api.OpenMayaAnim as oma
import maya.cmds as cmds

from ywta.deform import influence_cleanup
from ywta.deform import skin_io
from ywta.core import undo_utils


def _unique_nodes(nodes, node_type):
    """指定型のnodeを一意なロングパスへ解決する。"""
    if isinstance(nodes, str):
        nodes = [nodes]
    if not nodes:
        raise ValueError("{}を1つ以上指定してください。".format(node_type))
    result = []
    seen = set()
    for node in nodes:
        matches = cmds.ls(node, long=True, type=node_type) or []
        if len(matches) != 1:
            raise ValueError("{}を一意に解決できません: {}".format(node_type, node))
        node_uuid = (cmds.ls(matches[0], uuid=True) or [None])[0]
        if node_uuid not in seen:
            seen.add(node_uuid)
            result.append(matches[0])
    return result


def _clusters(meshes):
    """指定mesh群のskinClusterを重複なしで返す。"""
    if isinstance(meshes, str):
        meshes = [meshes]
    if not meshes:
        raise ValueError("スキンされたmeshを1つ以上指定してください。")
    result = []
    seen = set()
    for mesh in meshes:
        shape = skin_io._mesh_shape(mesh)
        cluster = skin_io._skin_cluster(shape)
        if cluster is None:
            raise ValueError("skinClusterが見つかりません: {}".format(shape))
        node_uuid = (cmds.ls(cluster, uuid=True) or [None])[0]
        if node_uuid not in seen:
            seen.add(node_uuid)
            result.append(cluster)
    return result


def _cluster_influences(cluster):
    """skinCluster influenceをUUID付きロングパスで返す。"""
    fn_skin = oma.MFnSkinCluster(skin_io._depend_node(cluster))
    result = []
    for path in fn_skin.influenceObjects():
        name = path.fullPathName()
        result.append((name, (cmds.ls(name, uuid=True) or [None])[0]))
    return result


def _selection():
    """現在選択から明示jointとmesh objectを分離する。"""
    selected = cmds.ls(selection=True, long=True, objectsOnly=True) or []
    joints = cmds.ls(selected, long=True, type="joint") or []
    meshes = []
    for node in selected:
        if cmds.nodeType(node) == "joint":
            continue
        try:
            shape = skin_io._mesh_shape(node)
        except ValueError:
            continue
        meshes.append(cmds.listRelatives(shape, parent=True, fullPath=True)[0])
    return meshes, joints


def add_influences(meshes, influences, lock_weights=False):
    """jointを既存ウェイトとjoint-global lockを保ってweight 0で追加する。"""
    if not isinstance(lock_weights, bool):
        raise ValueError("lock_weightsはboolにしてください。")
    clusters = _clusters(meshes)
    influences = _unique_nodes(influences, "joint")
    original_locks = {
        influence: bool(cmds.getAttr("{}.lockInfluenceWeights".format(influence)))
        if cmds.attributeQuery("lockInfluenceWeights", node=influence, exists=True)
        else False
        for influence in influences
    }
    plans = []
    for cluster in clusters:
        current = {node_uuid for _name, node_uuid in _cluster_influences(cluster)}
        plans.extend(
            (cluster, influence) for influence in influences if (cmds.ls(influence, uuid=True) or [None])[0] not in current
        )

    if not plans:
        return {"added": []}
    original_selection = cmds.ls(selection=True, long=True, flatten=True) or []
    undo_utils.require_enabled("Add Skin Influences")
    cmds.undoInfo(openChunk=True, chunkName="YWTA Add Skin Influences")
    failed = False
    added = []
    try:
        for cluster, influence in plans:
            cmds.skinCluster(
                cluster,
                edit=True,
                addInfluence=influence,
                weight=0.0,
                lockWeights=lock_weights or original_locks[influence],
            )
            added.append({"cluster": cluster, "influence": influence})
    except Exception:
        failed = True
        raise
    finally:
        try:
            skin_io._restore_selection(original_selection)
        except Exception:
            failed = True
            raise
        finally:
            cmds.undoInfo(closeChunk=True)
            if failed:
                cmds.undo()
    return {"added": added}


def remove_influences(meshes, influences, threshold=influence_cleanup.DEFAULT_THRESHOLD):
    """指定した未使用・unlocked influenceだけをskinClusterから削除する。"""
    threshold = influence_cleanup._threshold(threshold)
    clusters = _clusters(meshes)
    influences = _unique_nodes(influences, "joint")
    requested = {(cmds.ls(node, uuid=True) or [None])[0]: node for node in influences}
    plans = []
    for cluster in clusters:
        current = _cluster_influences(cluster)
        current_ids = {node_uuid for _name, node_uuid in current}
        candidates = {
            (cmds.ls(record["influence"], uuid=True) or [None])[0]
            for record in influence_cleanup.analyze_cluster(cluster, threshold=threshold)
        }
        bound_requested = current_ids.intersection(requested)
        used = bound_requested.difference(candidates)
        if used:
            raise ValueError("ウェイト使用中のinfluenceは削除できません: {}".format(requested[next(iter(used))]))
        locked = [requested[node_uuid] for node_uuid in bound_requested if influence_cleanup._is_locked(requested[node_uuid])]
        if locked:
            raise ValueError("locked influenceは削除できません: {}".format(locked[0]))
        if bound_requested and len(bound_requested) >= len(current_ids):
            raise ValueError("skinClusterの全influenceは削除できません: {}".format(cluster))
        plans.extend((cluster, requested[node_uuid]) for node_uuid in requested if node_uuid in bound_requested)

    if not plans:
        return {"removed": []}
    original_selection = cmds.ls(selection=True, long=True, flatten=True) or []
    undo_utils.require_enabled("Remove Skin Influences")
    cmds.undoInfo(openChunk=True, chunkName="YWTA Remove Skin Influences")
    failed = False
    removed = []
    try:
        for cluster, influence in plans:
            cmds.skinCluster(cluster, edit=True, removeInfluence=influence)
            removed.append({"cluster": cluster, "influence": influence})
    except Exception:
        failed = True
        raise
    finally:
        try:
            skin_io._restore_selection(original_selection)
        except Exception:
            failed = True
            raise
        finally:
            cmds.undoInfo(closeChunk=True)
            if failed:
                cmds.undo()
    return {"removed": removed}


def add_selected_influences():
    """現在選択jointを現在選択meshのskinClusterへ追加する。"""
    meshes, joints = _selection()
    result = add_influences(meshes, joints)
    if not result["added"]:
        cmds.warning("追加対象のskin influenceはありません。")
    return result


def remove_selected_influences():
    """現在選択jointを未使用時だけ現在選択meshから削除する。"""
    meshes, joints = _selection()
    result = remove_influences(meshes, joints)
    if not result["removed"]:
        cmds.warning("削除対象のskin influenceはありません。")
    return result
