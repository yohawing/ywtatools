"""Hair Tube Curve CageのMaya 2024操作導線。"""

from __future__ import annotations

import json
import re
import sys
from contextlib import contextmanager
from pathlib import Path

import maya.api.OpenMaya as om2
import maya.cmds as cmds
from ywta.core import undo_utils

try:
    from ywta_mesh_core import hair_tube as binding
except ImportError:
    _modules_dir = Path(__file__).resolve().parents[3] / "blender" / "modules"
    if str(_modules_dir) not in sys.path:
        sys.path.append(str(_modules_dir))
    from ywta_mesh_core import hair_tube as binding


_WINDOW_NAME = "ywta_hairTubeCurveCageWindow"
_CURVE_NAMES_ATTRIBUTE = "ywtaHairTubeCurveNames"
_ROOT_CAP_ATTRIBUTE = "ywtaHairTubeRootCapped"
_TIP_CAP_ATTRIBUTE = "ywtaHairTubeTipCapped"
_EDGE_PATTERN = re.compile(r"^(?P<object>.+)\.e\[(?P<index>\d+)\]$")


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
    """選択された3 edge以上からmeshと決定的なroot巡回順を返す。"""
    selected = cmds.ls(selection=True, flatten=True) or []
    parsed = []
    for component in selected:
        match = _EDGE_PATTERN.match(component)
        if match:
            parsed.append((match.group("object"), int(match.group("index"))))
    if len(parsed) < 3 or len({node for node, _index in parsed}) != 1:
        raise ValueError("同じmeshのroot断面3辺以上だけを選択してください")
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
    if len(adjacency) != len(parsed) or any(len(neighbours) != 2 for neighbours in adjacency.values()):
        raise ValueError("選択辺は3頂点以上の閉じたedge loopである必要があります")
    start = min(adjacency)
    cycle = [start, min(adjacency[start])]
    while len(cycle) < len(adjacency):
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


def _lerp_values(first, second, alpha):
    """同じ長さの数値列を線形補間する。"""
    return tuple(a * (1.0 - alpha) + b * alpha for a, b in zip(first, second))


def _source_face_vertex_index(function, face, vertex):
    """source face-vertexのflat indexを返す。"""
    vertices = function.getPolygonVertices(face)
    try:
        local_vertex = list(vertices).index(vertex)
    except ValueError as error:
        raise ValueError(f"source face {face}にsource vertex {vertex}がありません") from error
    return function.getFaceVertexIndex(face, local_vertex)


def _build_attribute_payload(source, generated):
    """source mappingからUV、color、material、skin weightを事前計算する。"""
    function = om2.MFnMesh(_mesh_dag_path(source))
    if len(generated.source_vertex_pairs) != len(generated.positions):
        raise ValueError("source vertex mappingの長さが生成頂点数と一致しません")
    if len(generated.source_faces) != len(generated.quads) or len(generated.source_corner_faces) != len(generated.quads) * 4:
        raise ValueError("source face mappingの長さが生成面またはloop数と一致しません")
    if any(vertex < 0 or vertex >= function.numVertices for pair in generated.source_vertex_pairs for vertex in pair) or any(
        face < 0 or face >= function.numPolygons for face in (*generated.source_faces, *generated.source_corner_faces)
    ):
        raise ValueError("現在のmeshはCurve Cageのsource mappingと一致しません")

    corner_sources = []
    for output_face, quad in enumerate(generated.quads):
        for corner, output_vertex in enumerate(quad):
            source_face = generated.source_corner_faces[output_face * 4 + corner]
            first, second = generated.source_vertex_pairs[output_vertex]
            alpha = generated.source_mapping[output_vertex][1]
            if alpha <= 0.0:
                second = first
                alpha = 0.0
            elif alpha >= 1.0:
                first = second
                alpha = 0.0
            corner_sources.append((source_face, first, second, alpha))

    uv_sets = []
    for uv_set in function.getUVSetNames():
        if function.numUVs(uv_set) == 0:
            continue
        values = []
        for face, first, second, alpha in corner_sources:
            vertices = list(function.getPolygonVertices(face))
            try:
                first_uv = function.getUV(function.getPolygonUVid(face, vertices.index(first), uv_set), uv_set)
                second_uv = function.getUV(function.getPolygonUVid(face, vertices.index(second), uv_set), uv_set)
            except RuntimeError as error:
                raise ValueError(f"UV set {uv_set}に未割り当てのsource cornerがあります") from error
            values.append(_lerp_values(first_uv, second_uv, alpha))
        uv_sets.append((uv_set, values))

    color_sets = []
    for color_set in function.getColorSetNames():
        source_colors = function.getFaceVertexColors(color_set)
        values = []
        for face, first, second, alpha in corner_sources:
            first_color = source_colors[_source_face_vertex_index(function, face, first)]
            second_color = source_colors[_source_face_vertex_index(function, face, second)]
            values.append(_lerp_values(first_color, second_color, alpha))
        color_sets.append(
            (
                color_set,
                function.isColorClamped(color_set),
                function.getColorRepresentation(color_set),
                values,
            )
        )

    shaders, shader_indices = function.getConnectedShaders(0)
    shader_names = [om2.MFnDependencyNode(shader).name() for shader in shaders]
    material_indices = [shader_indices[face] for face in generated.source_faces]

    skin_clusters = cmds.ls(cmds.listHistory(source) or [], type="skinCluster") or []
    if len(skin_clusters) > 1:
        raise ValueError("複数skinClusterを持つmeshのweight転送には対応していません")
    skin = None
    if skin_clusters:
        cluster = skin_clusters[0]
        influences = cmds.skinCluster(cluster, query=True, influence=True) or []
        source_weights = [
            cmds.skinPercent(cluster, f"{source}.vtx[{vertex}]", query=True, value=True)
            for vertex in range(function.numVertices)
        ]
        weights = []
        for (first, second), (_interval, alpha) in zip(generated.source_vertex_pairs, generated.source_mapping):
            interpolated = [a * (1.0 - alpha) + b * alpha for a, b in zip(source_weights[first], source_weights[second])]
            total = sum(interpolated)
            if total <= 1.0e-12:
                raise ValueError("生成頂点のskin weight合計が0です")
            weights.append([weight / total for weight in interpolated])
        skin = (influences, weights)

    return {
        "uv_sets": uv_sets,
        "color_sets": color_sets,
        "shader_names": shader_names,
        "material_indices": material_indices,
        "skin": skin,
    }


def _apply_attribute_payload(output, payload):
    """事前検証済み属性を生成meshへ適用する。"""
    function = om2.MFnMesh(_mesh_dag_path(output))
    face_counts = [4] * function.numPolygons
    uv_ids = list(range(function.numPolygons * 4))
    existing_uv_sets = set(function.getUVSetNames())
    for uv_set, values in payload["uv_sets"]:
        target_set = uv_set
        if uv_set not in existing_uv_sets:
            target_set = function.createUVSet(uv_set)
            existing_uv_sets.add(target_set)
        function.setUVs([value[0] for value in values], [value[1] for value in values], target_set)
        function.assignUVs(face_counts, uv_ids, target_set)

    existing_color_sets = set(function.getColorSetNames())
    face_ids = [face for face in range(function.numPolygons) for _corner in range(4)]
    vertex_ids = [vertex for quad in range(function.numPolygons) for vertex in function.getPolygonVertices(quad)]
    for color_set, clamped, representation, values in payload["color_sets"]:
        target_set = color_set
        if color_set not in existing_color_sets:
            target_set = function.createColorSet(color_set, clamped, representation)
            existing_color_sets.add(target_set)
        colors = [om2.MColor(value) for value in values]
        function.setCurrentColorSetName(target_set)
        function.setFaceVertexColors(colors, face_ids, vertex_ids, rep=representation)

    for shader_index, shader in enumerate(payload["shader_names"]):
        faces = [
            f"{output}.f[{face}]"
            for face, material_index in enumerate(payload["material_indices"])
            if material_index == shader_index
        ]
        if faces:
            cmds.sets(faces, edit=True, forceElement=shader)

    if payload["skin"] is not None:
        influences, weights = payload["skin"]
        cluster = cmds.skinCluster(influences, output, toSelectedBones=True, normalizeWeights=1)[0]
        for vertex, values in enumerate(weights):
            cmds.skinPercent(
                cluster,
                f"{output}.vtx[{vertex}]",
                transformValue=list(zip(influences, values)),
                normalize=True,
            )


def _create_curve_cage(source, generated):
    """station-major生成点からrailごとのdegree-1 curveを作る。"""
    station_count = len(generated.positions) // generated.rail_count
    matrix = cmds.xform(source, query=True, matrix=True, worldSpace=True)
    names = []
    base_name = source.split("|")[-1]
    for rail in range(generated.rail_count):
        points = [generated.positions[station * generated.rail_count + rail] for station in range(station_count)]
        curve = cmds.curve(degree=1, point=points, name=f"{base_name}_HairTubeRail{rail + 1}")
        cmds.xform(curve, matrix=matrix, worldSpace=True)
        names.append(curve)
    return names


def _update_curve_cage(output, names, generated):
    """再生成密度へCurve CV列を同期する。"""
    matrix = cmds.xform(output, query=True, matrix=True, worldSpace=True)
    if len(names) != generated.rail_count:
        raise ValueError("Curve Cage本数と生成rail数が一致しません")
    station_count = len(generated.positions) // generated.rail_count
    updated = []
    for rail, name in enumerate(names):
        cmds.delete(name)
        points = [generated.positions[station * generated.rail_count + rail] for station in range(station_count)]
        curve = cmds.curve(degree=1, point=points, name=name)
        cmds.xform(curve, matrix=matrix, worldSpace=True)
        updated.append(curve)
    return updated


def _set_curve_names(mesh, names):
    """生成meshへCurve Cage名をJSONで保存する。"""
    if not cmds.attributeQuery(_CURVE_NAMES_ATTRIBUTE, node=mesh, exists=True):
        cmds.addAttr(mesh, longName=_CURVE_NAMES_ATTRIBUTE, dataType="string")
    cmds.setAttr(f"{mesh}.{_CURVE_NAMES_ATTRIBUTE}", json.dumps(names), type="string")


def _set_cap_state(mesh, root_capped, tip_capped):
    """生成meshへroot/tip cap保持状態を保存する。"""
    for attribute, value in (
        (_ROOT_CAP_ATTRIBUTE, root_capped),
        (_TIP_CAP_ATTRIBUTE, tip_capped),
    ):
        if not cmds.attributeQuery(attribute, node=mesh, exists=True):
            cmds.addAttr(mesh, longName=attribute, attributeType="bool")
        cmds.setAttr(f"{mesh}.{attribute}", bool(value))


def _cap_state(mesh):
    """生成meshに保存したroot/tip cap状態を返す。"""
    return tuple(
        bool(cmds.getAttr(f"{mesh}.{attribute}")) if cmds.attributeQuery(attribute, node=mesh, exists=True) else False
        for attribute in (_ROOT_CAP_ATTRIBUTE, _TIP_CAP_ATTRIBUTE)
    )


def _read_curve_cage(mesh):
    """生成meshに紐づくCurve群をmesh object-spaceで読む。"""
    if not cmds.attributeQuery(_CURVE_NAMES_ATTRIBUTE, node=mesh, exists=True):
        raise ValueError("Hair Tube Curve Cage情報がありません")
    names = json.loads(cmds.getAttr(f"{mesh}.{_CURVE_NAMES_ATTRIBUTE}"))
    if len(names) < 3:
        raise ValueError("Hair Tube Curve Cageは3本以上必要です")
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
    """選択root loopから別meshとrailごとのCurve Cageを作る。"""
    source, root = _selected_root_cycle()
    positions, faces = _mesh_arrays(source)
    generated = binding.generate(positions, faces, root, target_segments=segments, fit_tolerance=fit_tolerance)
    attributes = _build_attribute_payload(source, generated)
    matrix = cmds.xform(source, query=True, matrix=True, worldSpace=True)
    with _undo_chunk("Create Hair Tube Curve Cage"):
        output = _create_mesh(f"{source.split('|')[-1]}_HairTube", generated, matrix)
        _apply_attribute_payload(output, attributes)
        names = _create_curve_cage(source, generated)
        _set_curve_names(output, names)
        _set_cap_state(output, generated.root_capped, generated.tip_capped)
        cmds.select(output, replace=True)
    return output


def rebuild_selected(segments=8, fit_tolerance=0.0):
    """選択した生成meshを編集済みCurve Cageから再生成する。"""
    selected = cmds.ls(selection=True, long=True, type="transform") or []
    if len(selected) != 1:
        raise ValueError("再生成するHair Tube meshを1つ選択してください")
    output = selected[0]
    names, rails = _read_curve_cage(output)
    root_capped, tip_capped = _cap_state(output)
    generated = binding.generate_from_rails(
        rails,
        target_segments=segments,
        fit_tolerance=fit_tolerance,
        root_capped=root_capped,
        tip_capped=tip_capped,
    )
    attributes = _build_attribute_payload(output, generated)
    matrix = cmds.xform(output, query=True, matrix=True, worldSpace=True)
    short_name = output.split("|")[-1]
    with _undo_chunk("Rebuild Hair Tube Curve Cage"):
        cmds.delete(output)
        rebuilt = _create_mesh(short_name, generated, matrix)
        _apply_attribute_payload(rebuilt, attributes)
        names = _update_curve_cage(rebuilt, names, generated)
        _set_curve_names(rebuilt, names)
        _set_cap_state(rebuilt, generated.root_capped, generated.tip_capped)
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
    root_capped, tip_capped = _cap_state(source)
    segments = _parse_lod_segments(segment_counts)
    generated_levels = []
    for segment_count in segments:
        generated = binding.generate_from_rails(
            rails,
            target_segments=segment_count,
            fit_tolerance=fit_tolerance,
            root_capped=root_capped,
            tip_capped=tip_capped,
        )
        generated_levels.append((segment_count, generated, _build_attribute_payload(source, generated)))
    matrix = cmds.xform(source, query=True, matrix=True, worldSpace=True)
    base_name = source.split("|")[-1]
    outputs = []
    with _undo_chunk("Generate Hair Tube LODs"):
        for segment_count, generated, attributes in generated_levels:
            output = _create_mesh(f"{base_name}_LOD{segment_count}", generated, matrix)
            _apply_attribute_payload(output, attributes)
            _set_curve_names(output, names)
            _set_cap_state(output, generated.root_capped, generated.tip_capped)
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
    cmds.text(label="生成meshとcurve群は別objectです。Undoで直前の操作を戻せます。")
    cmds.showWindow(window)
    return window
