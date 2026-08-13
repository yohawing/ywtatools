"""共有coreのmesh診断結果をMaya component選択へ反映する。"""

from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from pathlib import Path

import maya.api.OpenMaya as om2
import maya.cmds as cmds
from ywta.core import undo_utils

try:
    from ywta_mesh_core import mesh_diagnostics as binding
    from ywta_mesh_core import mesh_repair as repair_binding
except ImportError:
    _modules_dir = Path(__file__).resolve().parents[3] / "blender" / "modules"
    if str(_modules_dir) not in sys.path:
        sys.path.append(str(_modules_dir))
    from ywta_mesh_core import mesh_diagnostics as binding
    from ywta_mesh_core import mesh_repair as repair_binding


_WINDOW_NAME = "ywta_meshDiagnosticsWindow"
_REPAIR_MAPPING_ATTRIBUTE = "ywtaMeshRepairOldFaceToNew"


@contextmanager
def _undo_chunk(name):
    """Maya commandを単一Undo単位にまとめる。"""
    undo_utils.require_enabled(name)
    cmds.undoInfo(openChunk=True, chunkName=name)
    try:
        yield
    except Exception:
        cmds.undoInfo(closeChunk=True)
        if cmds.undoInfo(query=True, undoName=True) == name:
            cmds.undo()
        raise
    else:
        cmds.undoInfo(closeChunk=True)


def _selected_mesh():
    """選択された単一mesh transformを返す。"""
    selected = cmds.ls(selection=True, objectsOnly=True, long=True) or []
    transforms = []
    for node in selected:
        if cmds.nodeType(node) == "mesh":
            node = cmds.listRelatives(node, parent=True, fullPath=True)[0]
        shapes = cmds.listRelatives(node, shapes=True, noIntermediate=True, type="mesh") or []
        if shapes:
            transforms.append(node)
    transforms = list(dict.fromkeys(transforms))
    if len(transforms) != 1:
        raise ValueError("診断するmeshを1つ選択してください")
    return transforms[0]


def _mesh_arrays(transform):
    """Maya meshを共有core向け配列へ変換する。"""
    shapes = cmds.listRelatives(transform, shapes=True, noIntermediate=True, type="mesh", fullPath=True)
    selection = om2.MSelectionList()
    selection.add(shapes[0])
    function = om2.MFnMesh(selection.getDagPath(0))
    positions = [(point.x, point.y, point.z) for point in function.getPoints(om2.MSpace.kObject)]
    faces = [tuple(function.getPolygonVertices(face)) for face in range(function.numPolygons)]
    return function, positions, faces


def diagnose_selected(area_epsilon=1.0e-12):
    """選択meshを変更せず診断する。"""
    transform = _selected_mesh()
    _function, positions, faces = _mesh_arrays(transform)
    return transform, binding.diagnose(positions, faces, area_epsilon=area_epsilon)


def select_issue(issue, area_epsilon=1.0e-12):
    """診断分類に対応するcomponentを選択する。"""
    transform, report = diagnose_selected(area_epsilon)
    function, _positions, _faces = _mesh_arrays(transform)
    if issue == "zero_area":
        components = [f"{transform}.f[{face}]" for face in report.zero_area_faces]
    elif issue == "duplicate":
        components = [f"{transform}.f[{face}]" for face in report.duplicate_faces]
    elif issue == "bow_tie":
        components = [f"{transform}.vtx[{vertex}]" for vertex in report.bow_tie_vertices]
    else:
        if issue == "non_manifold":
            edge_pairs = set(report.non_manifold_edges)
        elif issue == "winding":
            edge_pairs = set(report.winding_conflict_edges)
        elif issue == "boundary":
            edge_pairs = {
                tuple(sorted((loop[index], loop[(index + 1) % len(loop)])))
                for loop in report.boundary_loops
                for index in range(len(loop))
            }
        else:
            raise ValueError(f"不明な診断分類です: {issue}")
        edge_pairs = {tuple(sorted(edge)) for edge in edge_pairs}
        iterator = om2.MItMeshEdge(function.object())
        edge_indices = []
        while not iterator.isDone():
            pair = tuple(sorted((iterator.vertexId(0), iterator.vertexId(1))))
            if pair in edge_pairs:
                edge_indices.append(iterator.index())
            iterator.next()
        components = [f"{transform}.e[{edge}]" for edge in edge_indices]
    cmds.select(components if components else transform, replace=True)
    return report


def safe_repair_selected(apply_changes=False, area_epsilon=1.0e-12):
    """安全修復planをpreviewし、明示時だけ単一Undoで適用する。"""
    transform = _selected_mesh()
    _function, positions, faces = _mesh_arrays(transform)
    plan = repair_binding.plan(positions, faces, area_epsilon=area_epsilon)
    removed = plan.removed_zero_area_faces + plan.removed_duplicate_faces
    affected = sorted(set(removed + plan.flipped_source_faces))
    if not apply_changes:
        cmds.select([f"{transform}.f[{face}]" for face in affected] or transform, replace=True)
        return plan
    if not plan.changed:
        return plan
    with _undo_chunk("Safe Mesh Repair"):
        if plan.flipped_source_faces:
            cmds.polyNormal(
                [f"{transform}.f[{face}]" for face in plan.flipped_source_faces],
                normalMode=0,
                userNormalMode=0,
                constructionHistory=False,
            )
        if removed:
            cmds.delete([f"{transform}.f[{face}]" for face in removed])
        if not cmds.attributeQuery(_REPAIR_MAPPING_ATTRIBUTE, node=transform, exists=True):
            cmds.addAttr(transform, longName=_REPAIR_MAPPING_ATTRIBUTE, dataType="string")
        cmds.setAttr(
            f"{transform}.{_REPAIR_MAPPING_ATTRIBUTE}",
            json.dumps(plan.old_face_to_new),
            type="string",
        )
        cmds.select(transform, replace=True)
    return plan


def show_options():
    """診断分類を選択表示するwindowを開く。"""
    if cmds.window(_WINDOW_NAME, exists=True):
        cmds.deleteUI(_WINDOW_NAME, window=True)
    window = cmds.window(_WINDOW_NAME, title="Mesh Diagnostics", widthHeight=(340, 260))
    cmds.columnLayout(adjustableColumn=True, rowSpacing=5, columnAttach=("both", 8))
    epsilon = cmds.floatFieldGrp(label="Area Epsilon", value1=1.0e-12, numberOfFields=1, precision=12)

    def run(issue):
        try:
            report = select_issue(issue, cmds.floatFieldGrp(epsilon, query=True, value1=True))
            cmds.inViewMessage(
                assistMessage=(f"Mesh Diagnostics: issues {report.issue_count}, boundary loops {len(report.boundary_loops)}"),
                position="midCenterTop",
                fade=True,
            )
        except (ValueError, FileNotFoundError, binding.MeshDiagnosticError) as error:
            cmds.warning(str(error))

    for label, issue in (
        ("Select Zero-area Faces", "zero_area"),
        ("Select Duplicate Faces", "duplicate"),
        ("Select Non-manifold Edges", "non_manifold"),
        ("Select Winding Conflicts", "winding"),
        ("Select Bow-tie Vertices", "bow_tie"),
        ("Select Boundary Loops", "boundary"),
    ):
        cmds.button(label=label, command=lambda _unused, value=issue: run(value))
    cmds.separator(height=8, style="in")

    def run_repair(apply_changes):
        try:
            plan = safe_repair_selected(
                apply_changes,
                cmds.floatFieldGrp(epsilon, query=True, value1=True),
            )
            action = "Applied" if apply_changes else "Dry-run"
            cmds.inViewMessage(
                assistMessage=(
                    f"{action}: remove {len(plan.removed_zero_area_faces) + len(plan.removed_duplicate_faces)}, "
                    f"flip {len(plan.flipped_source_faces)} faces"
                ),
                position="midCenterTop",
                fade=True,
            )
        except (ValueError, FileNotFoundError, repair_binding.MeshRepairError) as error:
            cmds.warning(str(error))

    cmds.button(label="Preview Safe Repair", command=lambda *_args: run_repair(False))
    cmds.button(label="Apply Safe Repair", command=lambda *_args: run_repair(True))
    cmds.text(label="診断はread-onlyです。ボタンで該当componentだけを選択します。")
    cmds.showWindow(window)
    return window
