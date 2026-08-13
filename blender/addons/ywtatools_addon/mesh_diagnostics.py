"""共有coreのmesh診断結果をBlender component選択へ反映する。"""

import json
import os
import sys

import bmesh
import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty
from bpy.types import Operator

try:
    from ywta_mesh_core import manifold_split as split_binding
    from ywta_mesh_core import mesh_diagnostics as binding
    from ywta_mesh_core import mesh_repair as repair_binding
except ImportError:
    _modules_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "modules"))
    if _modules_dir not in sys.path:
        sys.path.append(_modules_dir)
    from ywta_mesh_core import manifold_split as split_binding
    from ywta_mesh_core import mesh_diagnostics as binding
    from ywta_mesh_core import mesh_repair as repair_binding


_REPAIR_MAPPING_PROPERTY = "ywta_mesh_repair_old_face_to_new"
_SPLIT_MAPPING_PROPERTY = "ywta_manifold_split_source_vertex"


_ISSUES = (
    ("ZERO_AREA", "Zero-area Faces", "面積が閾値以下のfaceを選択"),
    ("DUPLICATE", "Duplicate Faces", "同じ頂点集合を持つfaceを選択"),
    ("NON_MANIFOLD", "Non-manifold Edges", "3面以上で共有されるedgeを選択"),
    ("WINDING", "Winding Conflicts", "隣接faceの向きが一致しないedgeを選択"),
    ("BOW_TIE", "Bow-tie Vertices", "複数のface fanを持つvertexを選択"),
    ("BOUNDARY", "Boundary Loops", "閉じたboundary loopを選択"),
)


def _mesh_arrays(mesh):
    """Blender Meshを共有core向け配列へ変換する。"""
    return [tuple(vertex.co) for vertex in mesh.vertices], [tuple(polygon.vertices) for polygon in mesh.polygons]


def _selected_components(report, issue):
    """issue種別に対応するcomponent IDを返す。"""
    if issue == "ZERO_AREA":
        return "FACE", set(report.zero_area_faces)
    if issue == "DUPLICATE":
        return "FACE", set(report.duplicate_faces)
    if issue == "NON_MANIFOLD":
        return "EDGE", {tuple(sorted(edge)) for edge in report.non_manifold_edges}
    if issue == "WINDING":
        return "EDGE", {tuple(sorted(edge)) for edge in report.winding_conflict_edges}
    if issue == "BOW_TIE":
        return "VERT", set(report.bow_tie_vertices)
    edges = set()
    for loop in report.boundary_loops:
        edges.update(tuple(sorted((loop[index], loop[(index + 1) % len(loop)]))) for index in range(len(loop)))
    return "EDGE", edges


class YWTA_OT_select_mesh_diagnostics(Operator):
    """選択meshを診断し、指定分類のcomponentを選択する。"""

    bl_idname = "ywta.select_mesh_diagnostics"
    bl_label = "Select Mesh Diagnostics"
    bl_description = "共有coreでmeshを診断し、指定した問題要素またはboundaryを選択します"
    bl_options = {"REGISTER", "UNDO"}

    issue: EnumProperty(name="Category", items=_ISSUES, default="NON_MANIFOLD")
    area_epsilon: FloatProperty(name="Area Epsilon", default=1.0e-12, min=0.0, precision=12)

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "MESH" and obj.mode in {"OBJECT", "EDIT"}

    def execute(self, context):
        obj = context.active_object
        was_edit = obj.mode == "EDIT"
        if was_edit:
            bpy.ops.object.mode_set(mode="OBJECT")
        try:
            positions, faces = _mesh_arrays(obj.data)
            report = binding.diagnose(positions, faces, area_epsilon=self.area_epsilon)
            component_type, identifiers = _selected_components(report, self.issue)
            bpy.ops.object.mode_set(mode="EDIT")
            bm = bmesh.from_edit_mesh(obj.data)
            for vertex in bm.verts:
                vertex.select = False
            for edge in bm.edges:
                edge.select = False
            for face in bm.faces:
                face.select = False
            if component_type == "FACE":
                for face in bm.faces:
                    face.select = face.index in identifiers
            elif component_type == "VERT":
                for vertex in bm.verts:
                    vertex.select = vertex.index in identifiers
            else:
                for edge in bm.edges:
                    edge.select = tuple(sorted(vertex.index for vertex in edge.verts)) in identifiers
            bmesh.update_edit_mesh(obj.data)
            bpy.context.tool_settings.mesh_select_mode = (
                component_type == "VERT",
                component_type == "EDGE",
                component_type == "FACE",
            )
        except (ValueError, FileNotFoundError, binding.MeshDiagnosticError) as error:
            if not was_edit and obj.mode == "EDIT":
                bpy.ops.object.mode_set(mode="OBJECT")
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report(
            {"INFO"},
            f"{self.issue}: {len(identifiers)} component、全問題 {report.issue_count} 件、boundary {len(report.boundary_loops)} loop",
        )
        return {"FINISHED"}

    def invoke(self, context, _event):
        """分類とzero-area閾値を確認する。"""
        return context.window_manager.invoke_props_dialog(self)


class YWTA_OT_safe_mesh_repair(Operator):
    """zero-area・重複faceを除去し、windingを安全範囲で整合する。"""

    bl_idname = "ywta.safe_mesh_repair"
    bl_label = "Safe Mesh Repair"
    bl_description = "dry-run確認後、zero-area・後発duplicate face除去とwinding整合をUndo可能に適用します"
    bl_options = {"REGISTER", "UNDO"}

    apply_changes: BoolProperty(name="Apply Changes", default=False)
    area_epsilon: FloatProperty(name="Area Epsilon", default=1.0e-12, min=0.0, precision=12)

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "MESH" and obj.mode in {"OBJECT", "EDIT"}

    def execute(self, context):
        obj = context.active_object
        if obj.mode == "EDIT":
            bpy.ops.object.mode_set(mode="OBJECT")
        try:
            positions, faces = _mesh_arrays(obj.data)
            plan = repair_binding.plan(positions, faces, area_epsilon=self.area_epsilon)
            affected = set(plan.removed_zero_area_faces + plan.removed_duplicate_faces + plan.flipped_source_faces)
            bpy.ops.object.mode_set(mode="EDIT")
            bm = bmesh.from_edit_mesh(obj.data)
            bm.faces.ensure_lookup_table()
            if not self.apply_changes:
                for face in bm.faces:
                    face.select = face.index in affected
                bmesh.update_edit_mesh(obj.data)
                self.report(
                    {"INFO"},
                    f"Dry-run: remove {len(plan.removed_zero_area_faces) + len(plan.removed_duplicate_faces)}、flip {len(plan.flipped_source_faces)} faces",
                )
                return {"FINISHED"}

            for face in plan.flipped_source_faces:
                bm.faces[face].normal_flip()
            removed = [bm.faces[face] for face in plan.removed_zero_area_faces + plan.removed_duplicate_faces]
            if removed:
                bmesh.ops.delete(bm, geom=removed, context="FACES_ONLY")
            bmesh.update_edit_mesh(obj.data, loop_triangles=True, destructive=bool(removed))
            obj[_REPAIR_MAPPING_PROPERTY] = json.dumps(plan.old_face_to_new)
        except (ValueError, FileNotFoundError, repair_binding.MeshRepairError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report(
            {"INFO"},
            f"remove {len(plan.removed_zero_area_faces) + len(plan.removed_duplicate_faces)}、flip {len(plan.flipped_source_faces)} facesを適用しました",
        )
        return {"FINISHED"}

    def invoke(self, context, _event):
        """既定dry-runで変更内容を確認する。"""
        return context.window_manager.invoke_props_dialog(self)


def _copy_mesh_for_split(obj, plan):
    """頂点写像を使ってUV・カラー・weightを保持した新meshを作る。"""
    source = obj.data
    if source.shape_keys is not None:
        raise ValueError("Shape Key付きmeshは分離できません。適用または複製してから実行してください")
    positions = [tuple(source.vertices[index].co) for index in plan.source_vertex_by_output]
    weights = [
        [(membership.group, membership.weight) for membership in source.vertices[index].groups]
        for index in plan.source_vertex_by_output
    ]
    group_names = [group.name for group in obj.vertex_groups]
    output = bpy.data.meshes.new(f"{source.name}_manifold")
    output.from_pydata(positions, [], plan.faces)
    for material in source.materials:
        output.materials.append(material)
    for source_face, output_face in zip(source.polygons, output.polygons):
        output_face.material_index = source_face.material_index
        output_face.use_smooth = source_face.use_smooth
    for source_layer in source.uv_layers:
        output_layer = output.uv_layers.new(name=source_layer.name)
        for index, source_uv in enumerate(source_layer.data):
            output_layer.data[index].uv = source_uv.uv
    for source_color in source.color_attributes:
        output_color = output.color_attributes.new(
            name=source_color.name,
            type=source_color.data_type,
            domain=source_color.domain,
        )
        source_indices = plan.source_vertex_by_output if source_color.domain == "POINT" else range(len(output_color.data))
        for output_index, source_index in enumerate(source_indices):
            output_color.data[output_index].color = source_color.data[source_index].color
    obj.data = output
    for name in group_names:
        obj.vertex_groups.new(name=name)
    for vertex, memberships in enumerate(weights):
        for group, weight in memberships:
            obj.vertex_groups[group].add([vertex], weight, "REPLACE")
    obj[_SPLIT_MAPPING_PROPERTY] = json.dumps(plan.source_vertex_by_output)


class YWTA_OT_split_mesh_manifold(Operator):
    """edge fanとvertex fanを属性保持した頂点複製で分離する。"""

    bl_idname = "ywta.split_mesh_manifold"
    bl_label = "Split Mesh to Manifold"
    bl_description = "dry-run確認後、非多様体edge fanとvertex fanを属性保持してUndo可能に分離します"
    bl_options = {"REGISTER", "UNDO"}

    apply_changes: BoolProperty(name="Apply Changes", default=False)

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "MESH" and obj.mode in {"OBJECT", "EDIT"}

    def execute(self, context):
        obj = context.active_object
        if obj.mode == "EDIT":
            bpy.ops.object.mode_set(mode="OBJECT")
        try:
            _positions, faces = _mesh_arrays(obj.data)
            plan = split_binding.plan(len(obj.data.vertices), faces)
            if not self.apply_changes:
                report = binding.diagnose(*_mesh_arrays(obj.data))
                bpy.ops.object.mode_set(mode="EDIT")
                bm = bmesh.from_edit_mesh(obj.data)
                split_edges = {tuple(sorted(edge)) for edge in report.non_manifold_edges}
                split_vertices = set(report.bow_tie_vertices)
                for edge in bm.edges:
                    edge.select = tuple(sorted(vertex.index for vertex in edge.verts)) in split_edges
                for vertex in bm.verts:
                    vertex.select = vertex.index in split_vertices
                bmesh.update_edit_mesh(obj.data)
                self.report(
                    {"INFO"},
                    f"Dry-run: split {len(plan.split_edges)} edges、{len(plan.split_vertices)} vertex fans",
                )
                return {"FINISHED"}
            if plan.changed:
                _copy_mesh_for_split(obj, plan)
        except (
            ValueError,
            FileNotFoundError,
            binding.MeshDiagnosticError,
            split_binding.ManifoldSplitError,
        ) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report(
            {"INFO"},
            f"split {len(plan.split_edges)} edges、{len(plan.split_vertices)} vertex fansを適用しました",
        )
        return {"FINISHED"}

    def invoke(self, context, _event):
        """既定dry-runで分離対象を確認する。"""
        return context.window_manager.invoke_props_dialog(self)


class YWTA_OT_fill_selected_boundary_loops(Operator):
    """完全に選択された閉boundary loopだけを明示的に穴埋めする。"""

    bl_idname = "ywta.fill_selected_boundary_loops"
    bl_label = "Fill Selected Boundary Loops"
    bl_description = "完全に選択した診断済みboundary loopだけをUndo可能なn-gonで閉じます"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "MESH" and obj.mode == "EDIT"

    def execute(self, context):
        obj = context.active_object
        bm = bmesh.from_edit_mesh(obj.data)
        selected_edges = {tuple(sorted(vertex.index for vertex in edge.verts)) for edge in bm.edges if edge.select}
        bpy.ops.object.mode_set(mode="OBJECT")
        try:
            report = binding.diagnose(*_mesh_arrays(obj.data))
            selected_loops = [
                loop
                for loop in report.boundary_loops
                if all(
                    tuple(sorted((loop[index], loop[(index + 1) % len(loop)]))) in selected_edges for index in range(len(loop))
                )
            ]
            if not selected_loops:
                raise ValueError("閉じたboundary loopを1つ以上、全edge選択してください")
            bpy.ops.object.mode_set(mode="EDIT")
            bm = bmesh.from_edit_mesh(obj.data)
            bm.verts.ensure_lookup_table()
            for loop in selected_loops:
                try:
                    bm.faces.new([bm.verts[vertex] for vertex in reversed(loop)])
                except ValueError as error:
                    raise ValueError("選択boundaryをn-gonとして追加できません") from error
            bmesh.update_edit_mesh(obj.data, loop_triangles=True, destructive=True)
        except (ValueError, FileNotFoundError, binding.MeshDiagnosticError) as error:
            if obj.mode != "EDIT":
                bpy.ops.object.mode_set(mode="EDIT")
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report({"INFO"}, f"{len(selected_loops)} boundary loopを穴埋めしました")
        return {"FINISHED"}


def _draw_mesh_menu(self, _context):
    self.layout.separator()
    self.layout.operator(YWTA_OT_select_mesh_diagnostics.bl_idname)
    self.layout.operator(YWTA_OT_safe_mesh_repair.bl_idname)
    self.layout.operator(YWTA_OT_split_mesh_manifold.bl_idname)
    self.layout.operator(YWTA_OT_fill_selected_boundary_loops.bl_idname)


def register():
    """operatorとEdit Modeメニューを登録する。"""
    bpy.utils.register_class(YWTA_OT_select_mesh_diagnostics)
    bpy.utils.register_class(YWTA_OT_safe_mesh_repair)
    bpy.utils.register_class(YWTA_OT_split_mesh_manifold)
    bpy.utils.register_class(YWTA_OT_fill_selected_boundary_loops)
    bpy.types.VIEW3D_MT_edit_mesh.append(_draw_mesh_menu)


def unregister():
    """operatorとEdit Modeメニューを解除する。"""
    bpy.types.VIEW3D_MT_edit_mesh.remove(_draw_mesh_menu)
    bpy.utils.unregister_class(YWTA_OT_fill_selected_boundary_loops)
    bpy.utils.unregister_class(YWTA_OT_split_mesh_manifold)
    bpy.utils.unregister_class(YWTA_OT_safe_mesh_repair)
    bpy.utils.unregister_class(YWTA_OT_select_mesh_diagnostics)
