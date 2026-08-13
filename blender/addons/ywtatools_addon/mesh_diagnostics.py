"""共有coreのmesh診断結果をBlender component選択へ反映する。"""

import os
import sys

import bmesh
import bpy
from bpy.props import EnumProperty, FloatProperty
from bpy.types import Operator

try:
    from ywta_mesh_core import mesh_diagnostics as binding
except ImportError:
    _modules_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "modules"))
    if _modules_dir not in sys.path:
        sys.path.append(_modules_dir)
    from ywta_mesh_core import mesh_diagnostics as binding


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


def _draw_mesh_menu(self, _context):
    self.layout.separator()
    self.layout.operator(YWTA_OT_select_mesh_diagnostics.bl_idname)


def register():
    """operatorとEdit Modeメニューを登録する。"""
    bpy.utils.register_class(YWTA_OT_select_mesh_diagnostics)
    bpy.types.VIEW3D_MT_edit_mesh.append(_draw_mesh_menu)


def unregister():
    """operatorとEdit Modeメニューを解除する。"""
    bpy.types.VIEW3D_MT_edit_mesh.remove(_draw_mesh_menu)
    bpy.utils.unregister_class(YWTA_OT_select_mesh_diagnostics)
