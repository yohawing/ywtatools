"""スキンウェイトをworld軸平面で安全にミラーする。"""

import maya.cmds as cmds

from ywta.core import undo_utils
from ywta.deform import skin_io


INFLUENCE_ASSOCIATIONS = {"closestJoint", "closestBone", "label", "name", "oneToOne"}
SURFACE_ASSOCIATIONS = {"closestPoint", "rayCast", "closestComponent"}


def _selected_mesh():
    """現在選択から単一の表示mesh transformを返す。"""
    meshes = []
    seen = set()
    for item in cmds.ls(selection=True, objectsOnly=True, long=True) or []:
        try:
            shape = skin_io._mesh_shape(item)
        except ValueError:
            continue
        transform = (cmds.listRelatives(shape, parent=True, fullPath=True) or [shape])[0]
        node_uuid = (cmds.ls(transform, uuid=True) or [None])[0]
        if node_uuid not in seen:
            seen.add(node_uuid)
            meshes.append(transform)
    if len(meshes) != 1:
        raise ValueError("ミラーするskinned meshを1つ選択してください。")
    return meshes[0]


def mirror_skin_weights(
    mesh,
    mirror_inverse=False,
    surface_association="closestPoint",
    influence_associations=("label", "name", "closestJoint"),
):
    """同一mesh内でYZ面を基準にスキンウェイトをミラーする。

    Args:
        mesh: 対象mesh transformまたはshape。
        mirror_inverse: Falseは+Xから-X、Trueは-Xから+Xへ転送する。
        surface_association: 対応頂点の検索方法。
        influence_associations: influence照合方法を優先順で指定する。

    Returns:
        実行したclusterと方向を含む辞書。
    """
    if not isinstance(mirror_inverse, bool):
        raise ValueError("mirror_inverseはboolで指定してください。")
    if surface_association not in SURFACE_ASSOCIATIONS:
        raise ValueError("surface associationが不正です: {}".format(surface_association))
    if not isinstance(influence_associations, (list, tuple)) or not influence_associations:
        raise ValueError("influence associationを1つ以上指定してください。")
    associations = []
    for association in influence_associations:
        if association not in INFLUENCE_ASSOCIATIONS:
            raise ValueError("influence associationが不正です: {}".format(association))
        if association not in associations:
            associations.append(association)

    shape = skin_io._mesh_shape(mesh)
    cluster = skin_io._skin_cluster(shape)
    if not cluster:
        raise ValueError("skinClusterが見つかりません: {}".format(shape))
    influences = cmds.skinCluster(cluster, query=True, influence=True) or []
    locked = [influence for influence in influences if cmds.getAttr(influence + ".lockInfluenceWeights")]
    if locked:
        raise ValueError("locked influenceがあるためミラーできません: {}".format(", ".join(locked)))

    selection = cmds.ls(selection=True, long=True) or []
    undo_utils.require_enabled("Mirror Skin Weights")
    cmds.undoInfo(openChunk=True, chunkName="YWTA Mirror Skin Weights YZ")
    failed = False
    try:
        cmds.copySkinWeights(
            sourceSkin=cluster,
            destinationSkin=cluster,
            mirrorMode="YZ",
            mirrorInverse=mirror_inverse,
            surfaceAssociation=surface_association,
            influenceAssociation=associations,
            normalize=True,
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
    return {
        "mesh": (cmds.listRelatives(shape, parent=True, fullPath=True) or [shape])[0],
        "skin_cluster": cluster,
        "direction": "negative_to_positive" if mirror_inverse else "positive_to_negative",
    }


def mirror_selected_positive_to_negative():
    """選択meshを+Xから-Xへミラーするメニュー入口。"""
    return mirror_skin_weights(_selected_mesh(), mirror_inverse=False)


def mirror_selected_negative_to_positive():
    """選択meshを-Xから+Xへミラーするメニュー入口。"""
    return mirror_skin_weights(_selected_mesh(), mirror_inverse=True)
