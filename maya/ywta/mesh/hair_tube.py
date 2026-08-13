"""Hair Tube Curve CageのMaya 2024操作導線。"""

from __future__ import annotations

import json
import re
import sys
from contextlib import contextmanager
from pathlib import Path

import maya.api.OpenMaya as om2
import maya.cmds as cmds

try:
    from ywta_mesh_core import hair_tube as binding
except ImportError:
    _modules_dir = Path(__file__).resolve().parents[3] / "blender" / "modules"
    if str(_modules_dir) not in sys.path:
        sys.path.append(str(_modules_dir))
    from ywta_mesh_core import hair_tube as binding


_WINDOW_NAME = "ywta_hairTubeCurveCageWindow"
_CURVE_NAMES_ATTRIBUTE = "ywtaHairTubeCurveNames"
_EDGE_PATTERN = re.compile(r"^(?P<object>.+)\.e\[(?P<index>\d+)\]$")


@contextmanager
def _undo_chunk(name):
    """Maya commandを単一Undo単位にまとめる。"""
    cmds.undoInfo(openChunk=True, chunkName=name)
    try:
        yield
    finally:
        cmds.undoInfo(closeChunk=True)


def _mesh_dag_path(node):
    """transformまたはshapeからmesh shapeのMDagPathを返す。"""
    shapes = cmds.listRelatives(node, shapes=True, noIntermediate=True, type="mesh") or []
    shape = node if cmds.nodeType(node) == "mesh" else (shapes[0] if shapes else None)
    if shape is None:
        raise ValueError(f"meshではありません: {node}")
    selection = om2.MSelectionList()
    selection.add(shape)
    return selection.getDagPath(0)


def _selected_root_cycle():
    """選択された4 edgeからmeshと決定的なroot巡回順を返す。"""
    selected = cmds.ls(selection=True, flatten=True) or []
    parsed = []
    for component in selected:
        match = _EDGE_PATTERN.match(component)
        if match:
            parsed.append((match.group("object"), int(match.group("index"))))
    if len(parsed) != 4 or len({node for node, _index in parsed}) != 1:
        raise ValueError("同じmeshのroot断面4辺だけを選択してください")
    node = parsed[0][0]
    dag_path = _mesh_dag_path(node)
    edge_iterator = om2.MItMeshEdge(dag_path)
    adjacency = {}
    for _node, edge_index in parsed:
        edge_iterator.setIndex(edge_index)
        first = edge_iterator.vertexId(0)
        second = edge_iterator.vertexId(1)
        adjacency.setdefault(first, []).append(second)
        adjacency.setdefault(second, []).append(first)
    if len(adjacency) != 4 or any(len(neighbours) != 2 for neighbours in adjacency.values()):
        raise ValueError("選択辺は4頂点の閉じたedge loopである必要があります")
    start = min(adjacency)
    cycle = [start, min(adjacency[start])]
    while len(cycle) < 4:
        candidates = [vertex for vertex in adjacency[cycle[-1]] if vertex != cycle[-2]]
        if len(candidates) != 1 or candidates[0] in cycle:
            raise ValueError("root edge loopの巡回順を一意に決定できません")
        cycle.append(candidates[0])
    if start not in adjacency[cycle[-1]]:
        raise ValueError("選択辺が閉じたroot loopではありません")
    transform = cmds.listRelatives(dag_path.fullPathName(), parent=True, fullPath=True)[0]
    return transform, cycle


def _mesh_arrays(transform):
    """Maya meshを共有core向けobject-space配列へ変換する。"""
    function = om2.MFnMesh(_mesh_dag_path(transform))
    positions = [(point.x, point.y, point.z) for point in function.getPoints(om2.MSpace.kObject)]
    faces = [tuple(function.getPolygonVertices(index)) for index in range(function.numPolygons)]
    return positions, faces


def _create_mesh(name, generated, matrix):
    """生成結果を新しいtransformとmesh shapeへ作成する。"""
    transform = cmds.createNode("transform", name=name)
    selection = om2.MSelectionList()
    selection.add(transform)
    parent = selection.getDependNode(0)
    points = [om2.MPoint(*point) for point in generated.positions]
    counts = [4] * len(generated.quads)
    connects = [vertex for quad in generated.quads for vertex in quad]
    mesh_object = om2.MFnMesh().create(points, counts, connects, parent=parent)
    shape = om2.MFnDagNode(mesh_object).fullPathName()
    cmds.rename(shape, f"{transform}Shape")
    cmds.xform(transform, matrix=matrix, worldSpace=True)
    cmds.sets(transform, edit=True, forceElement="initialShadingGroup")
    return transform


def _create_curve_cage(source, generated):
    """station-major生成点から4本のdegree-1 curveを作る。"""
    station_count = len(generated.positions) // 4
    matrix = cmds.xform(source, query=True, matrix=True, worldSpace=True)
    names = []
    base_name = source.split("|")[-1]
    for rail in range(4):
        points = [generated.positions[station * 4 + rail] for station in range(station_count)]
        curve = cmds.curve(degree=1, point=points, name=f"{base_name}_HairTubeRail{rail + 1}")
        cmds.xform(curve, matrix=matrix, worldSpace=True)
        names.append(curve)
    return names


def _set_curve_names(mesh, names):
    """生成meshへCurve Cage名をJSONで保存する。"""
    if not cmds.attributeQuery(_CURVE_NAMES_ATTRIBUTE, node=mesh, exists=True):
        cmds.addAttr(mesh, longName=_CURVE_NAMES_ATTRIBUTE, dataType="string")
    cmds.setAttr(f"{mesh}.{_CURVE_NAMES_ATTRIBUTE}", json.dumps(names), type="string")


def _read_curve_cage(mesh):
    """生成meshに紐づく4本のcurve CVをmesh object-spaceで読む。"""
    if not cmds.attributeQuery(_CURVE_NAMES_ATTRIBUTE, node=mesh, exists=True):
        raise ValueError("Hair Tube Curve Cage情報がありません")
    names = json.loads(cmds.getAttr(f"{mesh}.{_CURVE_NAMES_ATTRIBUTE}"))
    if len(names) != 4:
        raise ValueError("Hair Tube Curve Cageは4本必要です")
    output_inverse = om2.MMatrix(cmds.xform(mesh, query=True, matrix=True, worldSpace=True)).inverse()
    rails = []
    for name in names:
        if not cmds.objExists(name):
            raise ValueError(f"Curve Cageが見つかりません: {name}")
        shapes = cmds.listRelatives(name, shapes=True, noIntermediate=True, type="nurbsCurve") or []
        if len(shapes) != 1:
            raise ValueError(f"Curve Cageの構造が変わっています: {name}")
        selection = om2.MSelectionList()
        selection.add(shapes[0])
        dag_path = selection.getDagPath(0)
        function = om2.MFnNurbsCurve(dag_path)
        if function.degree != 1:
            raise ValueError("Curve Cageのdegreeは1のまま編集してください")
        transform = dag_path.inclusiveMatrix() * output_inverse
        rails.append([tuple(point * transform)[0:3] for point in function.cvPositions(om2.MSpace.kObject)])
    return names, rails


def create_from_selected_root(segments=8, fit_tolerance=0.0):
    """選択root loopから別meshと4本のCurve Cageを作る。"""
    source, root = _selected_root_cycle()
    positions, faces = _mesh_arrays(source)
    generated = binding.generate(positions, faces, root, target_segments=segments, fit_tolerance=fit_tolerance)
    matrix = cmds.xform(source, query=True, matrix=True, worldSpace=True)
    with _undo_chunk("Create Hair Tube Curve Cage"):
        output = _create_mesh(f"{source.split('|')[-1]}_HairTube", generated, matrix)
        names = _create_curve_cage(source, generated)
        _set_curve_names(output, names)
        cmds.select(output, replace=True)
    return output


def rebuild_selected(segments=8, fit_tolerance=0.0):
    """選択した生成meshを編集済みCurve Cageから再生成する。"""
    selected = cmds.ls(selection=True, long=True, type="transform") or []
    if len(selected) != 1:
        raise ValueError("再生成するHair Tube meshを1つ選択してください")
    output = selected[0]
    names, rails = _read_curve_cage(output)
    generated = binding.generate_from_rails(rails, target_segments=segments, fit_tolerance=fit_tolerance)
    matrix = cmds.xform(output, query=True, matrix=True, worldSpace=True)
    short_name = output.split("|")[-1]
    with _undo_chunk("Rebuild Hair Tube Curve Cage"):
        cmds.delete(output)
        rebuilt = _create_mesh(short_name, generated, matrix)
        _set_curve_names(rebuilt, names)
        cmds.select(rebuilt, replace=True)
    return rebuilt


def _parse_lod_segments(value):
    """comma区切りまたはsequenceを昇順のsegment数へ変換する。"""
    try:
        raw_values = value.split(",") if isinstance(value, str) else value
        segments = [int(item.strip() if isinstance(item, str) else item) for item in raw_values]
    except (TypeError, ValueError) as error:
        raise ValueError("LOD Segmentsはcomma区切りの整数で指定してください") from error
    if not segments or any(segment < 1 for segment in segments):
        raise ValueError("LOD Segmentsは1以上を1つ以上指定してください")
    if segments != sorted(set(segments)):
        raise ValueError("LOD Segmentsは重複なしの昇順で指定してください")
    return segments


def generate_lods_selected(segment_counts="2,4,8", fit_tolerance=0.0):
    """選択したHair TubeのCurve Cageから複数LODを別meshへ生成する。"""
    selected = cmds.ls(selection=True, long=True, type="transform") or []
    if len(selected) != 1:
        raise ValueError("LOD生成元のHair Tube meshを1つ選択してください")
    source = selected[0]
    names, rails = _read_curve_cage(source)
    segments = _parse_lod_segments(segment_counts)
    generated_levels = [
        (
            segment_count,
            binding.generate_from_rails(
                rails,
                target_segments=segment_count,
                fit_tolerance=fit_tolerance,
            ),
        )
        for segment_count in segments
    ]
    matrix = cmds.xform(source, query=True, matrix=True, worldSpace=True)
    base_name = source.split("|")[-1]
    outputs = []
    with _undo_chunk("Generate Hair Tube LODs"):
        for segment_count, generated in generated_levels:
            output = _create_mesh(f"{base_name}_LOD{segment_count}", generated, matrix)
            _set_curve_names(output, names)
            outputs.append(output)
        cmds.select(outputs, replace=True)
    return outputs


def show_options():
    """作成・再生成の最短導線を持つオプションwindowを表示する。"""
    if cmds.window(_WINDOW_NAME, exists=True):
        cmds.deleteUI(_WINDOW_NAME, window=True)
    window = cmds.window(_WINDOW_NAME, title="Hair Tube Curve Cage", widthHeight=(360, 220))
    cmds.columnLayout(adjustableColumn=True, rowSpacing=6, columnAttach=("both", 8))
    segments_field = cmds.intFieldGrp(label="Segments", value1=8, numberOfFields=1)
    tolerance_field = cmds.floatFieldGrp(label="Fit Tolerance", value1=0.0, numberOfFields=1)
    lod_field = cmds.textFieldGrp(label="LOD Segments", text="2,4,8")

    def values():
        return (
            cmds.intFieldGrp(segments_field, query=True, value1=True),
            cmds.floatFieldGrp(tolerance_field, query=True, value1=True),
        )

    def run_create(*_args):
        try:
            create_from_selected_root(*values())
        except (ValueError, FileNotFoundError, binding.HairTubeError) as error:
            cmds.warning(str(error))

    def run_rebuild(*_args):
        try:
            rebuild_selected(*values())
        except (ValueError, FileNotFoundError, binding.HairTubeError) as error:
            cmds.warning(str(error))

    def run_lods(*_args):
        try:
            generate_lods_selected(cmds.textFieldGrp(lod_field, query=True, text=True), values()[1])
        except (ValueError, FileNotFoundError, binding.HairTubeError) as error:
            cmds.warning(str(error))

    cmds.button(label="Create from Selected Root Edges", command=run_create, height=30)
    cmds.button(label="Rebuild Selected Hair Tube", command=run_rebuild, height=30)
    cmds.button(label="Generate LODs from Selected Hair Tube", command=run_lods, height=30)
    cmds.text(label="生成meshと4本のcurveは別objectです。Undoで直前の操作を戻せます。")
    cmds.showWindow(window)
    return window
