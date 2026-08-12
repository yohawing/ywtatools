"""複数のskinned meshを元データ非破壊で結合する。"""

from __future__ import absolute_import

import math

import maya.api.OpenMaya as om
import maya.api.OpenMayaAnim as oma
import maya.cmds as cmds

from ywta.deform import skin_io
from ywta.deform import skin_weight_command
from ywta.core import undo_utils


POSITION_TOLERANCE = 1.0e-6


def _absolute_name(name):
    """出力名をcurrent namespace非依存にする。"""
    return ":" + name.lstrip(":")


def _validated_output_name(name, label="name"):
    """Maya正規名と既存namespaceを検証した出力名を返す。"""
    if not isinstance(name, str) or not name.strip():
        raise ValueError("{}は空でないDAG short nameにしてください。".format(label))
    name = name.strip().lstrip(":")
    segments = name.split(":")
    if any(not segment or cmds.namespace(validateName=segment) != segment for segment in segments):
        raise ValueError("Mayaが自動変換する{}は使用できません: {}".format(label, name))
    if len(segments) > 1:
        namespace = ":".join(segments[:-1])
        if not cmds.namespace(exists=":" + namespace):
            raise ValueError("{}のnamespaceがありません: {}".format(label, namespace))
    return name


def _selected_meshes(meshes):
    """指定または選択されたmesh transformを一意なロングパスで返す。"""
    source = meshes if meshes is not None else cmds.ls(selection=True, long=True)
    if isinstance(source, (str, bytes)):
        raise ValueError("結合するskinned meshを2つ以上の列で指定してください。")
    if not source or len(source) < 2:
        raise ValueError("結合するskinned meshを2つ以上選択してください。")
    result = []
    seen = set()
    for mesh in source:
        shape = skin_io._mesh_shape(mesh)
        transform = (cmds.listRelatives(shape, parent=True, fullPath=True) or [None])[0]
        node_uuid = (cmds.ls(transform, uuid=True) or [None])[0]
        if node_uuid not in seen:
            seen.add(node_uuid)
            result.append(transform)
    if len(result) < 2:
        raise ValueError("結合するskinned meshを2つ以上選択してください。")
    return result


def _world_points(shape):
    """mesh頂点をworld-space tuple列で返す。"""
    return [
        (float(point.x), float(point.y), float(point.z))
        for point in om.MFnMesh(skin_io._dag_path(shape)).getPoints(om.MSpace.kWorld)
    ]


def _same_points(actual, expected, tolerance=POSITION_TOLERANCE):
    """2つの頂点列が有限かつ許容誤差内で一致するか判定する。"""
    if len(actual) != len(expected):
        return False
    return all(
        all(math.isfinite(value) for value in point + reference)
        and max(abs(value - target) for value, target in zip(point, reference)) <= tolerance
        for point, reference in zip(actual, expected)
    )


def _combined_weights(captures, influences):
    """source sparse weightsを結合先のphysical influence順に展開する。"""
    influence_index = {path: index for index, path in enumerate(influences)}
    weights = []
    for data in captures:
        source_paths = [item["path"] for item in data["influences"]]
        for sparse_row in data["weights"]:
            row = [0.0] * len(influences)
            for source_index, value in sparse_row:
                row[influence_index[source_paths[source_index]]] = float(value)
            weights.extend(row)
    return weights


def combine(meshes=None, name="combined_skinned_mesh"):
    """複数skinned meshを正確な頂点ウェイト付きで結合する。

    元meshは変更しない。polyUnite後の頂点順をworld座標で検証し、source頂点の
    単純連結でない場合は推測せず全操作を取り消す。

    Args:
        meshes: mesh transformまたはshapeの列。Noneは現在選択。
        name: 結合先transform名。

    Returns:
        mesh / skin_cluster / vertex_countを持つ結果辞書。
    """
    name = _validated_output_name(name)
    if cmds.objExists(_absolute_name(name)):
        raise ValueError("結合先名が既に存在します: {}".format(name))
    sources = _selected_meshes(meshes)
    captures = [skin_io.capture(source) for source in sources]
    expected_points = []
    influence_paths = []
    seen_influences = set()
    for source, data in zip(sources, captures):
        expected_points.extend(_world_points(skin_io._mesh_shape(source)))
        resolved = skin_io._resolve_influences(data["influences"])
        for influence in resolved:
            if influence not in seen_influences:
                seen_influences.add(influence)
                influence_paths.append(influence)
    skin_io._require_unlocked_nodes(influence_paths)

    original_selection = cmds.ls(selection=True, long=True) or []
    undo_utils.require_enabled("Combine Skinned Meshes")
    cmds.undoInfo(openChunk=True, chunkName="YWTA Combine Skinned Meshes")
    failed = False
    duplicates = []
    try:
        for source in sources:
            duplicates.extend(cmds.duplicate(source, returnRootsOnly=True))
        combined = cmds.polyUnite(
            duplicates,
            constructionHistory=False,
            mergeUVSets=True,
            name=_absolute_name(name),
        )[0]
        combined = (cmds.ls(combined, long=True) or [combined])[0]
        if combined.rsplit("|", 1)[-1] != name:
            raise RuntimeError("結合先名が競合しています: {} -> {}".format(name, combined))
        combined_shape = skin_io._mesh_shape(combined)
        actual_points = _world_points(combined_shape)
        if not _same_points(actual_points, expected_points):
            raise RuntimeError("polyUnite後の頂点順がsource順と一致しないため中止しました。")

        cluster = cmds.skinCluster(
            influence_paths,
            combined,
            toSelectedBones=True,
            normalizeWeights=1,
        )[0]
        fn_skin = oma.MFnSkinCluster(skin_io._depend_node(cluster))
        physical_paths = [path.fullPathName() for path in fn_skin.influenceObjects()]
        weights = _combined_weights(captures, physical_paths)
        vertex_count = len(expected_points)
        skin_weight_command.execute(
            cluster,
            combined_shape,
            range(vertex_count),
            range(len(physical_paths)),
            weights,
            normalize=False,
        )
        cmds.select(combined, replace=True)
    except Exception:
        failed = True
        raise
    finally:
        cmds.undoInfo(closeChunk=True)
        if failed:
            cmds.undo()
            valid_selection = [item for item in original_selection if cmds.objExists(item)]
            if valid_selection:
                cmds.select(valid_selection, replace=True)
            else:
                cmds.select(clear=True)
    return {
        "mesh": combined,
        "skin_cluster": cluster,
        "vertex_count": vertex_count,
        "sources": sources,
    }


def combine_selected():
    """現在選択されたskinned meshを既定名で結合する。"""
    return combine()
