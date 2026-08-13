"""AutoRemesher（クアッドリメッシュ）オペレータ。

選択中のメッシュオブジェクトから ``ywta_remesh`` バインディング経由でDLLを呼び出し、
リメッシュ結果を新規オブジェクトとして生成する。F9のRedoパネルでパラメータを
変更して再実行できる。
"""

import os
import sys

import bpy
from bpy.props import EnumProperty, FloatProperty, IntProperty, PointerProperty
from bpy.types import Object, Operator

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
_SOURCE_COLLECTION = "YWTA AutoRemesh Sources"
_SOURCE_POINTER = "ywta_autoremesh_source"
_SETTING_NAMES = (
    "target_count",
    "adaptivity",
    "edge_scaling",
    "model_type",
    "sharp_edge_degrees",
    "smooth_normal_degrees",
)


def _source_for(obj):
    """生成Objectなら保持元を、通常Objectなら自身を返す。"""
    source = getattr(obj, _SOURCE_POINTER, None)
    return source if source is not None and source.type == "MESH" else obj


def _source_collection(context):
    """元Objectを保持する非表示Collectionを返す。"""
    collection = bpy.data.collections.get(_SOURCE_COLLECTION)
    if collection is None:
        collection = bpy.data.collections.new(_SOURCE_COLLECTION)
        context.scene.collection.children.link(collection)
    collection.hide_viewport = True
    collection.hide_render = True
    return collection


def _archive_source(context, source, output_collections):
    """元Objectを専用Collectionへ移し、生成側のCollectionを維持する。"""
    archive = _source_collection(context)
    if source.name not in archive.objects:
        archive.objects.link(source)
    for collection in tuple(source.users_collection):
        if collection != archive:
            collection.objects.unlink(source)
    return output_collections


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

    sharp_edge_degrees: FloatProperty(
        name="シャープエッジ角度",
        description="シャープエッジと判定する角度（度）",
        default=90.0,
        min=0.0,
        max=180.0,
    )

    smooth_normal_degrees: FloatProperty(
        name="法線平滑化角度",
        description="法線を平滑化する角度（度）",
        default=0.0,
        min=0.0,
        max=180.0,
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "MESH"

    def invoke(self, context, event):
        # 実行前にパラメータ入力用ダイアログを表示する（実行後もF9のRedoパネルで再調整可能）
        obj = context.active_object
        if obj is not None and getattr(obj, _SOURCE_POINTER, None) is not None:
            for name in _SETTING_NAMES:
                key = f"ywta_autoremesh_{name}"
                if key in obj:
                    setattr(self, name, obj[key])
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "target_count")
        layout.prop(self, "adaptivity")
        layout.prop(self, "edge_scaling")
        layout.prop(self, "model_type")
        layout.prop(self, "sharp_edge_degrees")
        layout.prop(self, "smooth_normal_degrees")

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != "MESH":
            self.report({"ERROR"}, "メッシュオブジェクトを選択してください")
            return {"CANCELLED"}

        source = _source_for(obj)
        mesh = source.data
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
                sharp_edge_degrees=self.sharp_edge_degrees,
                smooth_normal_degrees=self.smooth_normal_degrees,
            )
        except FileNotFoundError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        except RuntimeError as e:
            self.report({"ERROR"}, f"AutoRemesherの実行に失敗しました: {e}")
            return {"CANCELLED"}

        # 元のmeshは保持し、生成Objectだけを作成または更新する。
        new_mesh_verts = [(out_vertices[i], out_vertices[i + 1], out_vertices[i + 2]) for i in range(0, len(out_vertices), 3)]

        new_mesh = bpy.data.meshes.new(f"{source.name}_remeshed")
        new_mesh.from_pydata(new_mesh_verts, [], out_faces)
        new_mesh.update()

        if source is obj:
            collections = tuple(source.users_collection) or (context.collection,)
            new_obj = bpy.data.objects.new(f"{source.name}_remeshed", new_mesh)
            for collection in collections:
                collection.objects.link(new_obj)
            _archive_source(context, source, collections)
            setattr(new_obj, _SOURCE_POINTER, source)
        else:
            new_obj = obj
            new_obj.data = new_mesh
        new_obj.matrix_world = source.matrix_world.copy()
        for name in _SETTING_NAMES:
            new_obj[f"ywta_autoremesh_{name}"] = getattr(self, name)

        for sel_obj in context.selected_objects:
            sel_obj.select_set(False)
        new_obj.select_set(True)
        context.view_layer.objects.active = new_obj

        self.report(
            {"INFO"},
            f"{source.name} を {len(new_mesh_verts)}頂点・{len(out_faces)}面にリメッシュしました",
        )
        return {"FINISHED"}


class YWTA_OT_reveal_autoremesh_source(Operator):
    """生成Objectが参照する元Objectを表示して選択する。"""

    bl_idname = "ywta.reveal_autoremesh_source"
    bl_label = "Reveal AutoRemesh Source"
    bl_description = "AutoRemesh生成Objectの保持元Collectionを表示し、元Objectを選択します"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and getattr(obj, _SOURCE_POINTER, None) is not None

    def execute(self, context):
        output = context.active_object
        source = getattr(output, _SOURCE_POINTER, None)
        if source is None:
            return {"CANCELLED"}
        archive = bpy.data.collections.get(_SOURCE_COLLECTION)
        if archive is not None:
            archive.hide_viewport = False
            archive.hide_render = False
        for selected in context.selected_objects:
            selected.select_set(False)
        source.hide_set(False)
        source.select_set(True)
        context.view_layer.objects.active = source
        self.report({"INFO"}, f"保持元 {source.name} を表示しました")
        return {"FINISHED"}


# オブジェクトメニューへのエントリ追加
def menu_func(self, context):
    self.layout.operator(YWTA_OT_autoremesh.bl_idname, text="AutoRemesh")
    self.layout.operator(YWTA_OT_reveal_autoremesh_source.bl_idname)


# 登録するクラスのリスト
classes = [
    YWTA_OT_autoremesh,
    YWTA_OT_reveal_autoremesh_source,
]


def register():
    setattr(Object, _SOURCE_POINTER, PointerProperty(type=Object))
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.VIEW3D_MT_object.append(menu_func)


def unregister():
    bpy.types.VIEW3D_MT_object.remove(menu_func)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    delattr(Object, _SOURCE_POINTER)


if __name__ == "__main__":
    register()
