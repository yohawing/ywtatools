"""Rustソルバーを使うEdit Modeメッシュスムージングオペレータ。"""

import os
import sys

import bmesh
import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty
from bpy.types import Operator

try:
    import ywta_mesh_smoothing.binding as binding
except ImportError:
    _modules_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "modules"))
    if _modules_dir not in sys.path:
        sys.path.append(_modules_dir)
    import ywta_mesh_smoothing.binding as binding


_MODE_ITEMS = (
    ("HC", "HC", "元形状を参照し、収縮を抑えてスムージング", 0),
    ("TAUBIN", "Taubin", "λ/μの二段パスで収縮を抑制", 1),
    ("UNIFORM", "Uniform", "均一Laplacianによる比較用スムージング", 2),
)
_MODE_VALUES = {
    "HC": binding.MODE_HC,
    "TAUBIN": binding.MODE_TAUBIN,
    "UNIFORM": binding.MODE_UNIFORM_LAPLACIAN,
}


def _is_closed_mesh(bm) -> bool:
    """全エッジがちょうど2面を共有する閉メッシュか判定する。"""
    return bool(bm.faces) and all(len(edge.link_faces) == 2 for edge in bm.edges)


def _is_selection_boundary(vertex) -> bool:
    """未選択領域またはメッシュ境界に接する頂点か判定する。"""
    return any(len(edge.link_faces) != 2 or not edge.other_vert(vertex).select for edge in vertex.link_edges)


class YWTA_OT_volume_smooth(Operator):
    """選択頂点をRustソルバーでスムージングする。"""

    bl_idname = "ywta.volume_smooth"
    bl_label = "Volume Preserving Smooth"
    bl_description = "選択頂点を収縮を抑えながらスムージングします"
    bl_options = {"REGISTER", "UNDO"}

    mode: EnumProperty(name="方式", items=_MODE_ITEMS, default="HC")
    iterations: IntProperty(name="反復回数", default=5, min=1, max=100)
    strength: FloatProperty(name="強さ", default=0.3, min=0.0, max=1.0)
    taubin_mu: FloatProperty(name="Taubin μ", default=-0.34, min=-1.0, max=-0.0001)
    hc_alpha: FloatProperty(name="HC α", default=0.0, min=0.0, max=1.0)
    hc_beta: FloatProperty(name="HC β", default=0.5, min=0.0, max=1.0)
    preserve_volume: BoolProperty(
        name="閉メッシュの体積を保持",
        description="閉メッシュでは初期符号付き体積へ補正し、開メッシュではHCのみ使います",
        default=True,
    )
    normal_only: BoolProperty(
        name="法線方向のみ",
        description="接線方向のドリフトを避け、元メッシュの頂点法線方向だけに移動します",
        default=False,
    )
    preserve_boundary: BoolProperty(
        name="選択境界を固定",
        description="未選択領域または開境界に接する選択頂点を固定します",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "MESH" and obj.mode == "EDIT"

    def draw(self, _context):
        layout = self.layout
        layout.prop(self, "mode")
        layout.prop(self, "iterations")
        layout.prop(self, "strength")
        if self.mode == "TAUBIN":
            layout.prop(self, "taubin_mu")
        if self.mode == "HC":
            layout.prop(self, "hc_alpha")
            layout.prop(self, "hc_beta")
        layout.prop(self, "preserve_volume")
        layout.prop(self, "normal_only")
        layout.prop(self, "preserve_boundary")

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != "MESH" or obj.mode != "EDIT":
            self.report({"ERROR"}, "メッシュのEdit Modeで実行してください")
            return {"CANCELLED"}

        mesh = obj.data
        bm = bmesh.from_edit_mesh(mesh)
        bm.verts.ensure_lookup_table()
        bm.verts.index_update()
        bm.normal_update()
        selected = [vertex for vertex in bm.verts if vertex.select]
        if not selected:
            self.report({"WARNING"}, "スムージングする頂点を選択してください")
            return {"CANCELLED"}

        positions = [component for vertex in bm.verts for component in vertex.co]
        edges = [index for edge in bm.edges for index in (edge.verts[0].index, edge.verts[1].index)]
        weights = [1.0 if vertex.select else 0.0 for vertex in bm.verts]
        constraint_modes = []
        directions = []
        for vertex in bm.verts:
            fixed = not vertex.select or (self.preserve_boundary and _is_selection_boundary(vertex))
            if fixed:
                constraint_modes.append(binding.CONSTRAINT_FIXED)
            elif self.normal_only:
                constraint_modes.append(binding.CONSTRAINT_NORMAL_ONLY)
            else:
                constraint_modes.append(binding.CONSTRAINT_FREE)
            normal = vertex.normal.normalized() if vertex.normal.length_squared > 0.0 else (0.0, 0.0, 1.0)
            directions.extend(normal)
        if all(mode == binding.CONSTRAINT_FIXED for mode in constraint_modes):
            self.report({"WARNING"}, "境界固定後に移動可能な選択頂点がありません")
            return {"CANCELLED"}

        closed_mesh = _is_closed_mesh(bm)
        triangles = []
        volume_correction = 0.0
        if self.preserve_volume and closed_mesh:
            bmesh.update_edit_mesh(mesh, loop_triangles=True, destructive=False)
            mesh.calc_loop_triangles()
            triangles = [index for triangle in mesh.loop_triangles for index in triangle.vertices]
            volume_correction = 1.0

        try:
            result = binding.smooth(
                positions,
                edges,
                mode=_MODE_VALUES[self.mode],
                iterations=self.iterations,
                strength=self.strength,
                taubin_mu=self.taubin_mu,
                hc_alpha=self.hc_alpha,
                hc_beta=self.hc_beta,
                volume_correction=volume_correction,
                triangles=triangles,
                vertex_weights=weights,
                constraint_modes=constraint_modes,
                constraint_directions=directions,
            )
        except (FileNotFoundError, ValueError, binding.MeshSmoothingError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}

        for vertex in bm.verts:
            start = vertex.index * 3
            vertex.co = result[start : start + 3]
        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
        if self.preserve_volume and not closed_mesh:
            self.report({"INFO"}, "開メッシュのため体積補正を省略し、選択方式だけを適用しました")
        return {"FINISHED"}


def menu_func(self, _context):
    """頂点コンテキストメニューへオペレータを追加する。"""
    self.layout.operator(YWTA_OT_volume_smooth.bl_idname)


classes = [YWTA_OT_volume_smooth]


def register():
    """Blenderへクラスとメニューを登録する。"""
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.VIEW3D_MT_edit_mesh_vertices.append(menu_func)


def unregister():
    """Blenderからクラスとメニューを解除する。"""
    bpy.types.VIEW3D_MT_edit_mesh_vertices.remove(menu_func)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
