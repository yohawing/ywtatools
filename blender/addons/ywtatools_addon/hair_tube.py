"""4-sided hair tubeをCurve Cageへ変換して再生成するBlenderオペレータ。"""

import json
import os
import sys

import bmesh
import bpy
from bpy.props import FloatProperty, IntProperty
from bpy.types import Operator

try:
    from ywta_mesh_core import hair_tube as binding
except ImportError:
    _modules_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "modules"))
    if _modules_dir not in sys.path:
        sys.path.append(_modules_dir)
    from ywta_mesh_core import hair_tube as binding


_CURVE_NAMES_PROPERTY = "ywta_hair_tube_curve_names"


def _selected_root_cycle(bm):
    """選択された4辺から決定的なroot巡回順を返す。"""
    bm.verts.ensure_lookup_table()
    bm.verts.index_update()
    bm.edges.ensure_lookup_table()
    selected_edges = [edge for edge in bm.edges if edge.select]
    if len(selected_edges) != 4:
        raise ValueError("root断面を構成する4辺だけを選択してください")
    adjacency = {}
    for edge in selected_edges:
        first, second = (vertex.index for vertex in edge.verts)
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
    return cycle


def _mesh_arrays(mesh):
    """Blender Meshを共有core向け配列へ変換する。"""
    return [tuple(vertex.co) for vertex in mesh.vertices], [tuple(polygon.vertices) for polygon in mesh.polygons]


def _link_object_like_source(context, source, obj):
    """sourceと同じcollectionへobjectをリンクする。"""
    collections = source.users_collection or (context.collection,)
    for collection in collections:
        collection.objects.link(obj)


def _replace_mesh(obj, generated):
    """生成meshを新しいdatablockへ置換する。"""
    mesh = bpy.data.meshes.new(f"{obj.name}_mesh")
    mesh.from_pydata(generated.positions, [], generated.quads)
    mesh.update()
    old_mesh = obj.data
    obj.data = mesh
    if old_mesh is not None and old_mesh.users == 0:
        bpy.data.meshes.remove(old_mesh)


def _create_curve_cage(context, source, generated):
    """station-major生成点から4本のpoly curveを作る。"""
    station_count = len(generated.positions) // 4
    names = []
    for rail in range(4):
        curve = bpy.data.curves.new(f"{source.name}_HairTubeRail{rail + 1}", "CURVE")
        curve.dimensions = "3D"
        curve.resolution_u = 2
        spline = curve.splines.new("POLY")
        spline.points.add(station_count - 1)
        for station, point in enumerate(spline.points):
            position = generated.positions[station * 4 + rail]
            point.co = (*position, 1.0)
        curve_obj = bpy.data.objects.new(curve.name, curve)
        curve_obj.matrix_world = source.matrix_world.copy()
        _link_object_like_source(context, source, curve_obj)
        names.append(curve_obj.name)
    return names


def _read_curve_cage(obj):
    """生成objectに記録された4本のCurveからrail-major点列を読む。"""
    try:
        names = json.loads(obj[_CURVE_NAMES_PROPERTY])
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("Hair Tube Curve Cage情報がありません") from error
    if len(names) != 4:
        raise ValueError("Hair Tube Curve Cageは4本必要です")
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


class YWTA_OT_hair_tube_create(Operator):
    """選択root loopから編集可能なCurve Cageと別meshを作る。"""

    bl_idname = "ywta.hair_tube_create"
    bl_label = "Create Hair Tube Curve Cage"
    bl_description = "選択した4辺root loopから編集可能なCurve Cageと別meshを生成します"
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

        mesh = bpy.data.meshes.new(f"{source.name}_HairTube")
        mesh.from_pydata(generated.positions, [], generated.quads)
        mesh.update()
        output = bpy.data.objects.new(mesh.name, mesh)
        output.matrix_world = source.matrix_world.copy()
        _link_object_like_source(context, source, output)
        curve_names = _create_curve_cage(context, source, generated)
        output[_CURVE_NAMES_PROPERTY] = json.dumps(curve_names, ensure_ascii=True)
        for selected in context.selected_objects:
            selected.select_set(False)
        output.select_set(True)
        context.view_layer.objects.active = output
        self.report(
            {"INFO"},
            f"{len(generated.positions)}頂点・{len(generated.quads)}面と4本のCurve Cageを生成しました",
        )
        return {"FINISHED"}

    def invoke(self, context, _event):
        """生成前に密度とfit toleranceを確認する。"""
        return context.window_manager.invoke_props_dialog(self)


class YWTA_OT_hair_tube_rebuild(Operator):
    """編集済みCurve Cageと現在密度から生成meshを更新する。"""

    bl_idname = "ywta.hair_tube_rebuild"
    bl_label = "Rebuild from Hair Tube Curve Cage"
    bl_description = "編集した4本のCurve Cageを読み戻して生成meshを更新します"
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
            generated = binding.generate_from_rails(rails, target_segments=self.segments, fit_tolerance=self.fit_tolerance)
        except (ValueError, FileNotFoundError, binding.HairTubeError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        _replace_mesh(obj, generated)
        self.report({"INFO"}, f"Curve Cageから{len(generated.positions)}頂点へ再生成しました")
        return {"FINISHED"}

    def invoke(self, context, _event):
        """再生成前に密度とfit toleranceを編集する。"""
        return context.window_manager.invoke_props_dialog(self)


def edit_menu_func(self, _context):
    """Edit Meshメニューへ作成操作を追加する。"""
    self.layout.separator()
    self.layout.operator(YWTA_OT_hair_tube_create.bl_idname)


def object_menu_func(self, _context):
    """Objectメニューへ再生成操作を追加する。"""
    self.layout.separator()
    self.layout.operator(YWTA_OT_hair_tube_rebuild.bl_idname)


classes = [YWTA_OT_hair_tube_create, YWTA_OT_hair_tube_rebuild]


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
