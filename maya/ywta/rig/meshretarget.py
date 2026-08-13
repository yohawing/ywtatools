"""Retarget meshes fit on a source mesh to a modified version of the source mesh.

The RBF formulation is adapted from PyGeM's MIT-licensed RBF implementation:
https://github.com/mathLab/PyGeM/blob/1daf6f0ec47eff05f66b6c10cba046c2c6a8deee/pygem/rbf.py
See ``PyGeM-LICENSE.rst`` in this directory.

Example Usage
=============

    retarget("source_body", "new_body", ["shirt", "pants"], rbf=RBF.linear)

"""

import time
import numpy as np

import maya.api.OpenMaya as OpenMaya
import maya.cmds as cmds
from ywta.core import maya_utils, node_utils, undo_utils
from ywta.rig.rbf_solver import (  # noqa: F401
    RBF,
    RbfSolver,
    get_distance_matrix,
    get_weight_matrix,
)


def retarget(
    source,
    target,
    shapes,
    rbf=None,
    radius=0.5,
    stride=1,
    max_control_points=None,
    progress=None,
    cancelled=None,
):
    """対応するbody meshから複数のfollowerを一括変形する。

    Args:
        source: 変形前のbody mesh。
        target: sourceと同一topologyの変形後body mesh。
        shapes: 複製して変形するfollower meshの列。
        rbf: 使用するRBF kernel。
        radius: RBFのsmoothing parameter。
        stride: source/targetのcontrol pointを間引く間隔。
        max_control_points: Farthest-point samplingで選ぶ最大control point数。
            指定時はstrideを使用しない。
        progress: ``(phase, done, total)`` を受け取る進捗callback。
        cancelled: キャンセル要求時にTrueを返すcallback。

    Returns:
        変形結果として作成したduplicate名のlist。
    """
    start_time = time.time()
    source, target, shapes = _preflight_inputs(source, target, shapes)
    source_points = points_to_np_array(source, stride if max_control_points is None else 1)
    target_points = points_to_np_array(target, stride if max_control_points is None else 1)

    solver = RbfSolver.fit(
        source_points,
        target_points,
        rbf=rbf,
        radius=radius,
        max_control_points=max_control_points,
        progress=progress,
        cancelled=cancelled,
    )

    point_sets = [points_to_np_array(shape) for shape in shapes]
    deformed_sets = solver.transform_many(point_sets, progress, cancelled)

    # MPoint変換も編集前に完了させ、scene編集中に計算例外が発生しないようにする。
    transformed_points = [[OpenMaya.MPoint(*point) for point in deformed] for deformed in deformed_sets]
    created = []
    undo_open = False
    try:
        if _maya_cmd_available("undoInfo"):
            undo_utils.require_enabled("RBF Mesh Retarget")
            cmds.undoInfo(openChunk=True, chunkName="YWTA RBF Mesh Retarget")
            undo_open = True
        for shape, points in zip(shapes, transformed_points):
            short_name = shape.rsplit("|", 1)[-1]
            duplicate_result = cmds.duplicate(
                shape,
                name="{}_{}_{}".format(short_name, radius, solver.rbf.__name__),
            )
            if not duplicate_result:
                raise RuntimeError("RBF retarget duplicateを作成できませんでした: {}".format(shape))
            duplicate = duplicate_result[0]
            created.append(duplicate)
            set_points(duplicate, points)
    except Exception:
        # chunkを閉じてから一度だけUndoし、直前の別操作を巻き戻さない。
        if undo_open:
            cmds.undoInfo(closeChunk=True)
            undo_open = False
            if created:
                cmds.undo()
        raise
    finally:
        if undo_open:
            cmds.undoInfo(closeChunk=True)

    end_time = time.time()
    print("Transferred in {} seconds".format(end_time - start_time))
    return created


def _maya_cmd_available(name):
    """テスト用の軽量Mayaスタブを含め、cmds APIの有無を確認する。"""
    return callable(getattr(cmds, name, None))


def _preflight_inputs(source, target, shapes):
    """全入力を検証し、Maya上では一意なtransform名へ解決する。"""
    if source is None or target is None:
        raise ValueError("sourceとtargetは必須です")
    shapes = list(shapes or [])
    if not shapes:
        raise ValueError("少なくとも1つのfollower meshが必要です")

    requested = [source, target] + shapes
    requested_keys = [str(item) for item in requested]
    if requested_keys[0] == requested_keys[1]:
        raise ValueError("sourceとtargetは別meshである必要があります")
    if len(set(requested_keys[2:])) != len(shapes):
        raise ValueError("follower meshの重複は許可されません")
    if requested_keys[0] in requested_keys[2:] or requested_keys[1] in requested_keys[2:]:
        raise ValueError("source/targetをfollowerとして指定できません")

    # Maya未導入の数値テストでは、Maya固有のpreflightを実行できない。
    # 実Mayaでは必ず以下の全検証を通過する。
    if not _maya_cmd_available("objExists"):
        return source, target, shapes

    resolved = [_resolve_mesh(item) for item in requested]
    resolved_keys = [item[0] for item in resolved]
    if resolved_keys[0] == resolved_keys[1]:
        raise ValueError("sourceとtargetは同じmeshを指せません")
    if len(set(resolved_keys[2:])) != len(shapes):
        raise ValueError("follower meshの重複は許可されません")
    if resolved_keys[0] in resolved_keys[2:] or resolved_keys[1] in resolved_keys[2:]:
        raise ValueError("source/targetをfollowerとして指定できません")

    source_transform, source_shape = resolved[0]
    target_transform, target_shape = resolved[1]
    source_topology = _mesh_topology(source_shape)
    target_topology = _mesh_topology(target_shape)
    if source_topology != target_topology:
        raise ValueError("sourceとtargetのtopology（頂点数またはface connectivity）が一致しません")

    matrices = [_world_matrix(item[0]) for item in resolved]
    first_matrix = matrices[0]
    if any(matrix != first_matrix for matrix in matrices[1:]):
        raise ValueError("全input meshのworld matrixが一致しません")

    return source_transform, target_transform, [item[0] for item in resolved[2:]]


def _resolve_mesh(node):
    """曖昧でないmesh transformを解決し、参照nodeを拒否する。"""
    if not isinstance(node, str) or not node:
        raise ValueError("mesh名は空でない文字列で指定してください")
    matches = cmds.ls(node, long=True) or []
    if len(matches) != 1:
        raise ValueError("mesh名が存在しないか曖昧です: {}".format(node))
    candidate = matches[0]
    if cmds.referenceQuery(candidate, isNodeReferenced=True):
        raise ValueError("参照meshはRBF retargetの入力にできません: {}".format(candidate))
    node_type = cmds.nodeType(candidate)
    if node_type == "transform":
        shapes = (
            cmds.listRelatives(
                candidate,
                shapes=True,
                noIntermediate=True,
                fullPath=True,
                type="mesh",
            )
            or []
        )
        if len(shapes) != 1:
            raise ValueError("mesh shapeが一意に解決できません: {}".format(candidate))
        shape = shapes[0]
        transform = candidate
    elif node_type == "mesh":
        shape = candidate
        parents = cmds.listRelatives(shape, parent=True, fullPath=True, type="transform") or []
        if len(parents) != 1:
            raise ValueError("mesh transformが一意に解決できません: {}".format(candidate))
        transform = parents[0]
    else:
        raise ValueError("mesh transformまたはmesh shapeを指定してください: {}".format(candidate))
    if _maya_cmd_available("getAttr") and cmds.getAttr("{}.intermediateObject".format(shape)):
        raise ValueError("中間mesh shapeは入力にできません: {}".format(shape))
    if cmds.referenceQuery(shape, isNodeReferenced=True) or cmds.referenceQuery(transform, isNodeReferenced=True):
        raise ValueError("参照meshはRBF retargetの入力にできません: {}".format(candidate))
    return transform, shape


def _mesh_topology(shape):
    """meshの頂点数とface vertex順を返す。"""
    path = maya_utils.get_dag_path(shape)
    mesh_fn = OpenMaya.MFnMesh(path)
    vertex_count = int(mesh_fn.numVertices)
    polygon_count = int(mesh_fn.numPolygons)
    faces = tuple(tuple(int(index) for index in mesh_fn.getPolygonVertices(face_index)) for face_index in range(polygon_count))
    return vertex_count, faces


def _world_matrix(transform):
    """transformのworld matrixを比較用のimmutable tupleへ変換する。"""
    matrix = cmds.xform(transform, query=True, worldSpace=True, matrix=True)
    values = tuple(float(value) for value in matrix)
    if len(values) != 16:
        raise ValueError("world matrixを取得できませんでした: {}".format(transform))
    return values


def points_to_np_array(mesh, stride=1):
    points = get_points(mesh)
    sparse_points = [OpenMaya.MPoint(p) for p in points][::stride]
    np_points = np.array([[p.x, p.y, p.z] for p in sparse_points])
    return np_points


def get_points(mesh):
    path = maya_utils.get_dag_path(node_utils.get_shape(mesh))
    mesh_fn = OpenMaya.MFnMesh(path)
    return mesh_fn.getPoints()


def set_points(mesh, points):
    path = maya_utils.get_dag_path(node_utils.get_shape(mesh))
    mesh_fn = OpenMaya.MFnMesh(path)
    mesh_fn.setPoints(points)
