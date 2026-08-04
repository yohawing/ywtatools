"""AutoRemesher（クアッドリメッシュ）オペレータ。

選択中のメッシュオブジェクトから ``ywta_remesh`` バインディング経由でDLLを呼び出し、
リメッシュ結果を新規オブジェクトとして生成する。F9のRedoパネルでパラメータを
変更して再実行できる。
"""

import os
import sys

import bpy
from bpy.types import Operator
from bpy.props import IntProperty, FloatProperty, EnumProperty

try:
    import ywta_remesh.binding as binding
except ImportError:
    # scriptsディレクトリにblender/が登録されていない環境向けのフォールバック。
    # このファイル(blender/addons/ywtatools_addon/autoremesher.py)から
    # 2階層上がblender/なので、そこにmodules/を追加する。
    _modules_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "modules"))
    if _modules_dir not in sys.path:
        sys.path.append(_modules_dir)
    import ywta_remesh.binding as binding


# AutoRemesherのモデルタイプ（C ABI の model_type に対応）
_MODEL_TYPE_ITEMS = (
    ("ORGANIC", "Organic", "有機的な形状向けのリメッシュ", 0),
    ("HARDSURFACE", "Hard Surface", "工業製品などのハードサーフェス向けのリメッシュ", 1),
)
_MODEL_TYPE_VALUES = {identifier: value for identifier, _, _, value in _MODEL_TYPE_ITEMS}


# AutoRemesherでクアッドリメッシュを実行するオペレーター
class YWTA_OT_autoremesh(Operator):
    bl_idname = "ywta.autoremesh"
    bl_label = "AutoRemesh"
    bl_description = "選択中のメッシュをAutoRemesherでクアッドリメッシュします"
    bl_options = {"REGISTER", "UNDO"}

    target_count: IntProperty(
        name="目標三角形数",
        description="リメッシュ後の目標三角形数",
        default=8000,
        min=100,
    )

    adaptivity: FloatProperty(
        name="適応度",
        description="細部の形状変化への追従度（0.0〜1.0）",
        default=1.0,
        min=0.0,
        max=1.0,
    )

    edge_scaling: FloatProperty(
        name="エッジスケール",
        description="生成されるクアッドのエッジ長スケーリング",
        default=1.0,
        min=0.0001,
    )

    model_type: EnumProperty(
        name="モデルタイプ",
        description="リメッシュ対象の形状の種類",
        items=_MODEL_TYPE_ITEMS,
        default="ORGANIC",
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "MESH"

    def invoke(self, context, event):
        # 実行前にパラメータ入力用ダイアログを表示する（実行後もF9のRedoパネルで再調整可能）
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "target_count")
        layout.prop(self, "adaptivity")
        layout.prop(self, "edge_scaling")
        layout.prop(self, "model_type")

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != "MESH":
            self.report({"ERROR"}, "メッシュオブジェクトを選択してください")
            return {"CANCELLED"}

        mesh = obj.data
        mesh.calc_loop_triangles()

        vertex_count = len(mesh.vertices)
        vertices = [0.0] * (vertex_count * 3)
        mesh.vertices.foreach_get("co", vertices)

        tri_count = len(mesh.loop_triangles)
        tri_indices = [0] * (tri_count * 3)
        mesh.loop_triangles.foreach_get("vertices", tri_indices)

        try:
            out_vertices, out_faces = binding.remesh(
                vertices,
                tri_indices,
                target_count=self.target_count,
                scaling=self.edge_scaling,
                adaptivity=self.adaptivity,
                model_type=_MODEL_TYPE_VALUES[self.model_type],
            )
        except FileNotFoundError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        except RuntimeError as e:
            self.report({"ERROR"}, f"AutoRemesherの実行に失敗しました: {e}")
            return {"CANCELLED"}

        # 結果を新規メッシュオブジェクトとして生成（元のメッシュはローカル空間のまま維持）
        new_mesh_verts = [
            (out_vertices[i], out_vertices[i + 1], out_vertices[i + 2]) for i in range(0, len(out_vertices), 3)
        ]

        new_mesh = bpy.data.meshes.new(f"{obj.name}_remeshed")
        new_mesh.from_pydata(new_mesh_verts, [], out_faces)
        new_mesh.update()

        new_obj = bpy.data.objects.new(f"{obj.name}_remeshed", new_mesh)
        new_obj.matrix_world = obj.matrix_world.copy()

        # 元オブジェクトと同じコレクションにリンクする
        collections = obj.users_collection or (context.collection,)
        for collection in collections:
            collection.objects.link(new_obj)

        for sel_obj in context.selected_objects:
            sel_obj.select_set(False)
        new_obj.select_set(True)
        context.view_layer.objects.active = new_obj

        self.report(
            {"INFO"},
            f"{obj.name} を {len(new_mesh_verts)}頂点・{len(out_faces)}面にリメッシュしました",
        )
        return {"FINISHED"}


# オブジェクトメニューへのエントリ追加
def menu_func(self, context):
    self.layout.operator(YWTA_OT_autoremesh.bl_idname, text="AutoRemesh")


# 登録するクラスのリスト
classes = [
    YWTA_OT_autoremesh,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.VIEW3D_MT_object.append(menu_func)


def unregister():
    bpy.types.VIEW3D_MT_object.remove(menu_func)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
