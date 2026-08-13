"""N-sided hair tubeをCurve Cageへ変換して再生成するBlenderオペレータ。"""

import json
import os
import sys

import bmesh
import bpy
from bpy.props import FloatProperty, IntProperty, StringProperty
from bpy.types import Operator

try:
    from ywta_mesh_core import hair_tube as binding
except ImportError:
    _modules_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "modules"))
    if _modules_dir not in sys.path:
        sys.path.append(_modules_dir)
    from ywta_mesh_core import hair_tube as binding


_CURVE_NAMES_PROPERTY = "ywta_hair_tube_curve_names"
_ROOT_CAP_PROPERTY = "ywta_hair_tube_root_capped"
_TIP_CAP_PROPERTY = "ywta_hair_tube_tip_capped"


def _selected_root_cycle(bm):
    """選択された3辺以上から決定的なroot巡回順を返す。"""
    bm.verts.ensure_lookup_table()
    bm.verts.index_update()
    bm.edges.ensure_lookup_table()
    selected_edges = [edge for edge in bm.edges if edge.select]
    if len(selected_edges) < 3:
        raise ValueError("root断面を構成する3辺以上だけを選択してください")
    adjacency = {}
    for edge in selected_edges:
        first, second = (vertex.index for vertex in edge.verts)
        adjacency.setdefault(first, []).append(second)
        adjacency.setdefault(second, []).append(first)
    if len(adjacency) != len(selected_edges) or any(len(neighbours) != 2 for neighbours in adjacency.values()):
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
    return cycle


def _mesh_arrays(mesh):
    """Blender Meshを共有core向け配列へ変換する。"""
    return [tuple(vertex.co) for vertex in mesh.vertices], [tuple(polygon.vertices) for polygon in mesh.polygons]


def _link_object_like_source(context, source, obj):
    """sourceと同じcollectionへobjectをリンクする。"""
    collections = source.users_collection or (context.collection,)
    for collection in collections:
        collection.objects.link(obj)


def _replace_mesh(obj, generated, attributes=None):
    """生成meshを新しいdatablockへ置換する。"""
    mesh = bpy.data.meshes.new(f"{obj.name}_mesh")
    mesh.from_pydata(generated.positions, [], generated.quads)
    mesh.update()
    old_mesh = obj.data
    obj.data = mesh
    if attributes is not None:
        _apply_attribute_payload(obj, attributes)
    if old_mesh is not None and old_mesh.users == 0:
        bpy.data.meshes.remove(old_mesh)


def _parse_lod_segments(value):
    """comma区切りを昇順かつ重複なしのsegment数へ変換する。"""
    try:
        segments = [int(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as error:
        raise ValueError("LOD Segmentsはcomma区切りの整数で指定してください") from error
    if not segments or any(segment < 1 for segment in segments):
        raise ValueError("LOD Segmentsは1以上を1つ以上指定してください")
    if segments != sorted(set(segments)):
        raise ValueError("LOD Segmentsは重複なしの昇順で指定してください")
    return segments


def _create_generated_object(context, source, name, generated, attributes=None):
    """sourceと同じtransform・collectionに生成mesh objectを作る。"""
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(generated.positions, [], generated.quads)
    mesh.update()
    output = bpy.data.objects.new(name, mesh)
    output.matrix_world = source.matrix_world.copy()
    _link_object_like_source(context, source, output)
    try:
        if attributes is not None:
            _apply_attribute_payload(output, attributes)
    except Exception:
        bpy.data.objects.remove(output, do_unlink=True)
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
        raise
    return output


def _lerp_values(first, second, alpha):
    """同じ長さの数値列を線形補間する。"""
    return tuple(a * (1.0 - alpha) + b * alpha for a, b in zip(first, second))


def _source_loop(mesh, face_index, vertex_index):
    """source face内のvertexに対応するloop indexを返す。"""
    polygon = mesh.polygons[face_index]
    for loop_index in polygon.loop_indices:
        if mesh.loops[loop_index].vertex_index == vertex_index:
            return loop_index
    raise ValueError(f"source face {face_index}にsource vertex {vertex_index}がありません")


def _build_attribute_payload(source, generated):
    """source mappingからUV、color、material、vertex groupを事前計算する。"""
    mesh = source.data
    has_attributes = bool(len(source.vertex_groups) or len(mesh.materials) or len(mesh.uv_layers) or len(mesh.color_attributes))
    if not has_attributes:
        return None
    if len(generated.source_vertex_pairs) != len(generated.positions):
        raise ValueError("source vertex mappingの長さが生成頂点数と一致しません")
    if len(generated.source_faces) != len(generated.quads):
        raise ValueError("source face mappingの長さが生成面数と一致しません")
    if len(generated.source_corner_faces) != len(generated.quads) * 4:
        raise ValueError("source corner face mappingの長さが生成loop数と一致しません")
    if any(vertex < 0 or vertex >= len(mesh.vertices) for pair in generated.source_vertex_pairs for vertex in pair) or any(
        face < 0 or face >= len(mesh.polygons) for face in (*generated.source_faces, *generated.source_corner_faces)
    ):
        raise ValueError("現在のmeshはCurve Cageのsource mappingと一致しません")

    output_loop_sources = []
    for output_face, quad in enumerate(generated.quads):
        for corner, output_vertex in enumerate(quad):
            source_face = generated.source_corner_faces[output_face * 4 + corner]
            first, second = generated.source_vertex_pairs[output_vertex]
            alpha = generated.source_mapping[output_vertex][1]
            if alpha <= 0.0:
                source_loop = _source_loop(mesh, source_face, first)
                output_loop_sources.append((source_loop, source_loop, 0.0))
                continue
            if alpha >= 1.0:
                source_loop = _source_loop(mesh, source_face, second)
                output_loop_sources.append((source_loop, source_loop, 0.0))
                continue
            output_loop_sources.append(
                (
                    _source_loop(mesh, source_face, first),
                    _source_loop(mesh, source_face, second),
                    alpha,
                )
            )

    uv_layers = []
    for layer in mesh.uv_layers:
        values = [
            _lerp_values(layer.data[first].uv, layer.data[second].uv, alpha) for first, second, alpha in output_loop_sources
        ]
        uv_layers.append((layer.name, values))

    color_layers = []
    for layer in mesh.color_attributes:
        if layer.domain == "CORNER":
            values = [
                _lerp_values(layer.data[first].color, layer.data[second].color, alpha)
                for first, second, alpha in output_loop_sources
            ]
        elif layer.domain == "POINT":
            values = [
                _lerp_values(layer.data[first].color, layer.data[second].color, alpha)
                for (first, second), (_interval, alpha) in zip(generated.source_vertex_pairs, generated.source_mapping)
            ]
        else:
            continue
        color_layers.append((layer.name, layer.data_type, layer.domain, values))

    armatures = [
        modifier.object for modifier in source.modifiers if modifier.type == "ARMATURE" and modifier.object is not None
    ]
    bone_names = {bone.name for armature in armatures for bone in armature.data.bones}
    group_weights = {}
    for group in source.vertex_groups:
        values = []
        for (first, second), (_interval, alpha) in zip(generated.source_vertex_pairs, generated.source_mapping):
            try:
                first_weight = group.weight(first)
            except RuntimeError:
                first_weight = 0.0
            try:
                second_weight = group.weight(second)
            except RuntimeError:
                second_weight = 0.0
            values.append(first_weight * (1.0 - alpha) + second_weight * alpha)
        group_weights[group.name] = values
    skin_groups = [name for name in group_weights if name in bone_names]
    for vertex in range(len(generated.positions)):
        total = sum(group_weights[name][vertex] for name in skin_groups)
        if skin_groups and total <= 1.0e-12:
            raise ValueError(f"生成頂点{vertex}のskin weight合計が0です")
        if total > 0.0:
            for name in skin_groups:
                group_weights[name][vertex] /= total

    return {
        "materials": list(mesh.materials),
        "material_indices": [mesh.polygons[source_face].material_index for source_face in generated.source_faces],
        "uv_layers": uv_layers,
        "color_layers": color_layers,
        "group_weights": group_weights,
        "armatures": armatures,
    }


def _apply_attribute_payload(output, payload):
    """事前検証済み属性を生成objectへ適用する。"""
    mesh = output.data
    for material in payload["materials"]:
        mesh.materials.append(material)
    for polygon, material_index in zip(mesh.polygons, payload["material_indices"]):
        polygon.material_index = material_index
    for name, values in payload["uv_layers"]:
        layer = mesh.uv_layers.new(name=name)
        for datum, value in zip(layer.data, values):
            datum.uv = value
    for name, data_type, domain, values in payload["color_layers"]:
        layer = mesh.color_attributes.new(name=name, type=data_type, domain=domain)
        for datum, value in zip(layer.data, values):
            datum.color = value
    output.vertex_groups.clear()
    for name, weights in payload["group_weights"].items():
        group = output.vertex_groups.new(name=name)
        for vertex, weight in enumerate(weights):
            if weight > 0.0:
                group.add([vertex], weight, "REPLACE")
    for modifier in list(output.modifiers):
        if modifier.type == "ARMATURE":
            output.modifiers.remove(modifier)
    for index, armature in enumerate(payload["armatures"]):
        modifier = output.modifiers.new(name=f"HairTubeArmature{index + 1}", type="ARMATURE")
        modifier.object = armature


def _create_curve_cage(context, source, generated):
    """station-major生成点からrailごとのpoly curveを作る。"""
    station_count = len(generated.positions) // generated.rail_count
    names = []
    for rail in range(generated.rail_count):
        curve = bpy.data.curves.new(f"{source.name}_HairTubeRail{rail + 1}", "CURVE")
        curve.dimensions = "3D"
        curve.resolution_u = 2
        spline = curve.splines.new("POLY")
        spline.points.add(station_count - 1)
        for station, point in enumerate(spline.points):
            position = generated.positions[station * generated.rail_count + rail]
            point.co = (*position, 1.0)
        curve_obj = bpy.data.objects.new(curve.name, curve)
        curve_obj.matrix_world = source.matrix_world.copy()
        _link_object_like_source(context, source, curve_obj)
        names.append(curve_obj.name)
    return names


def _read_curve_cage(obj):
    """生成objectに記録されたCurve群からrail-major点列を読む。"""
    try:
        names = json.loads(obj[_CURVE_NAMES_PROPERTY])
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("Hair Tube Curve Cage情報がありません") from error
    if len(names) < 3:
        raise ValueError("Hair Tube Curve Cageは3本以上必要です")
    rails = []
    for name in names:
        curve_obj = bpy.data.objects.get(name)
        if curve_obj is None or curve_obj.type != "CURVE" or len(curve_obj.data.splines) != 1:
            raise ValueError(f"Curve Cageが見つからないか構造が変わっています: {name}")
        spline = curve_obj.data.splines[0]
        if spline.type != "POLY":
            raise ValueError("Curve Cageのspline typeはPOLYのまま編集してください")
        transform = obj.matrix_world.inverted_safe() @ curve_obj.matrix_world
        rails.append([tuple(transform @ point.co.xyz) for point in spline.points])
    return rails


def _update_curve_cage(obj, generated):
    """再生成密度へCurve CageのCV列を同期し、次回mappingを一致させる。"""
    names = json.loads(obj[_CURVE_NAMES_PROPERTY])
    if len(names) != generated.rail_count:
        raise ValueError("Curve Cage本数と生成rail数が一致しません")
    station_count = len(generated.positions) // generated.rail_count
    for rail, name in enumerate(names):
        curve_obj = bpy.data.objects[name]
        curve_obj.matrix_world = obj.matrix_world.copy()
        curve = curve_obj.data
        curve.splines.clear()
        spline = curve.splines.new("POLY")
        spline.points.add(station_count - 1)
        for station, point in enumerate(spline.points):
            point.co = (*generated.positions[station * generated.rail_count + rail], 1.0)


class YWTA_OT_hair_tube_create(Operator):
    """選択root loopから編集可能なCurve Cageと別meshを作る。"""

    bl_idname = "ywta.hair_tube_create"
    bl_label = "Create Hair Tube Curve Cage"
    bl_description = "選択した3辺以上のroot loopから編集可能なCurve Cageと別meshを生成します"
    bl_options = {"REGISTER", "UNDO"}

    segments: IntProperty(name="Segments", default=8, min=1, max=2048)
    fit_tolerance: FloatProperty(name="Fit Tolerance", default=0.0, min=0.0, precision=6)

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "MESH" and obj.mode == "EDIT"

    def execute(self, context):
        source = context.active_object
        bm = bmesh.from_edit_mesh(source.data)
        try:
            root = _selected_root_cycle(bm)
            bpy.ops.object.mode_set(mode="OBJECT")
            positions, faces = _mesh_arrays(source.data)
            generated = binding.generate(
                positions, faces, root, target_segments=self.segments, fit_tolerance=self.fit_tolerance
            )
        except (ValueError, FileNotFoundError, binding.HairTubeError) as error:
            if source.mode != "EDIT":
                bpy.ops.object.mode_set(mode="EDIT")
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}

        try:
            attributes = _build_attribute_payload(source, generated)
        except ValueError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        try:
            output = _create_generated_object(context, source, f"{source.name}_HairTube", generated, attributes)
            curve_names = _create_curve_cage(context, source, generated)
        except (ValueError, RuntimeError) as error:
            if "output" in locals():
                bpy.data.objects.remove(output, do_unlink=True)
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        output[_CURVE_NAMES_PROPERTY] = json.dumps(curve_names, ensure_ascii=True)
        output[_ROOT_CAP_PROPERTY] = generated.root_capped
        output[_TIP_CAP_PROPERTY] = generated.tip_capped
        for selected in context.selected_objects:
            selected.select_set(False)
        output.select_set(True)
        context.view_layer.objects.active = output
        self.report(
            {"INFO"},
            f"{len(generated.positions)}頂点・{len(generated.quads)}面と{generated.rail_count}本のCurve Cageを生成しました",
        )
        return {"FINISHED"}

    def invoke(self, context, _event):
        """生成前に密度とfit toleranceを確認する。"""
        return context.window_manager.invoke_props_dialog(self)


class YWTA_OT_hair_tube_rebuild(Operator):
    """編集済みCurve Cageと現在密度から生成meshを更新する。"""

    bl_idname = "ywta.hair_tube_rebuild"
    bl_label = "Rebuild from Hair Tube Curve Cage"
    bl_description = "編集したCurve Cage群を読み戻して生成meshを更新します"
    bl_options = {"REGISTER", "UNDO"}

    segments: IntProperty(name="Segments", default=8, min=1, max=2048)
    fit_tolerance: FloatProperty(name="Fit Tolerance", default=0.0, min=0.0, precision=6)

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "MESH" and _CURVE_NAMES_PROPERTY in obj

    def execute(self, context):
        obj = context.active_object
        try:
            rails = _read_curve_cage(obj)
            generated = binding.generate_from_rails(
                rails,
                target_segments=self.segments,
                fit_tolerance=self.fit_tolerance,
                root_capped=bool(obj.get(_ROOT_CAP_PROPERTY, False)),
                tip_capped=bool(obj.get(_TIP_CAP_PROPERTY, False)),
            )
            attributes = _build_attribute_payload(obj, generated)
        except (ValueError, FileNotFoundError, binding.HairTubeError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        _replace_mesh(obj, generated, attributes)
        _update_curve_cage(obj, generated)
        self.report({"INFO"}, f"Curve Cageから{len(generated.positions)}頂点へ再生成しました")
        return {"FINISHED"}

    def invoke(self, context, _event):
        """再生成前に密度とfit toleranceを編集する。"""
        return context.window_manager.invoke_props_dialog(self)


class YWTA_OT_hair_tube_generate_lods(Operator):
    """同じCurve Cageから複数密度の別meshを一括生成する。"""

    bl_idname = "ywta.hair_tube_generate_lods"
    bl_label = "Generate Hair Tube LODs"
    bl_description = "編集済みCurve Cageから複数密度のLODを別Objectとして生成します"
    bl_options = {"REGISTER", "UNDO"}

    segments: StringProperty(name="LOD Segments", default="2,4,8")
    fit_tolerance: FloatProperty(name="Fit Tolerance", default=0.0, min=0.0, precision=6)

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "MESH" and _CURVE_NAMES_PROPERTY in obj

    def execute(self, context):
        source = context.active_object
        try:
            segment_counts = _parse_lod_segments(self.segments)
            rails = _read_curve_cage(source)
            generated_levels = []
            for segments in segment_counts:
                generated = binding.generate_from_rails(
                    rails,
                    target_segments=segments,
                    fit_tolerance=self.fit_tolerance,
                    root_capped=bool(source.get(_ROOT_CAP_PROPERTY, False)),
                    tip_capped=bool(source.get(_TIP_CAP_PROPERTY, False)),
                )
                generated_levels.append((segments, generated, _build_attribute_payload(source, generated)))
        except (ValueError, FileNotFoundError, binding.HairTubeError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}

        curve_names = source[_CURVE_NAMES_PROPERTY]
        outputs = []
        try:
            for segments, generated, attributes in generated_levels:
                output = _create_generated_object(
                    context,
                    source,
                    f"{source.name}_LOD{segments}",
                    generated,
                    attributes,
                )
                output[_CURVE_NAMES_PROPERTY] = curve_names
                output[_ROOT_CAP_PROPERTY] = generated.root_capped
                output[_TIP_CAP_PROPERTY] = generated.tip_capped
                outputs.append(output)
        except (ValueError, RuntimeError) as error:
            for output in outputs:
                bpy.data.objects.remove(output, do_unlink=True)
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        for selected in context.selected_objects:
            selected.select_set(False)
        for output in outputs:
            output.select_set(True)
        context.view_layer.objects.active = outputs[-1]
        self.report({"INFO"}, f"{len(outputs)}個のHair Tube LODを生成しました")
        return {"FINISHED"}

    def invoke(self, context, _event):
        """一括生成前にLOD密度列を編集する。"""
        return context.window_manager.invoke_props_dialog(self)


def edit_menu_func(self, _context):
    """Edit Meshメニューへ作成操作を追加する。"""
    self.layout.separator()
    self.layout.operator(YWTA_OT_hair_tube_create.bl_idname)


def object_menu_func(self, _context):
    """Objectメニューへ再生成操作を追加する。"""
    self.layout.separator()
    self.layout.operator(YWTA_OT_hair_tube_rebuild.bl_idname)
    self.layout.operator(YWTA_OT_hair_tube_generate_lods.bl_idname)


classes = [
    YWTA_OT_hair_tube_create,
    YWTA_OT_hair_tube_rebuild,
    YWTA_OT_hair_tube_generate_lods,
]


def register():
    """オペレータとメニューを登録する。"""
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.VIEW3D_MT_edit_mesh.append(edit_menu_func)
    bpy.types.VIEW3D_MT_object.append(object_menu_func)


def unregister():
    """オペレータとメニューを解除する。"""
    bpy.types.VIEW3D_MT_object.remove(object_menu_func)
    bpy.types.VIEW3D_MT_edit_mesh.remove(edit_menu_func)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
