import bpy
from bpy.types import Panel, Operator, PropertyGroup
from bpy.props import StringProperty, BoolProperty, PointerProperty


# ShapeKeyのリネーム用プロパティグループ
class ShapeKeyRenameProperties(PropertyGroup):
    search_pattern: StringProperty(name="検索", description="検索するShapeKey名のパターン", default="")

    replace_pattern: StringProperty(name="置換", description="置換後のShapeKey名のパターン", default="")

    case_sensitive: BoolProperty(
        name="大文字/小文字を区別",
        description="大文字と小文字を区別して検索する",
        default=False,
    )

    selected_only: BoolProperty(
        name="選択したオブジェクトのみ",
        description="選択したオブジェクトのShapeKeyのみを対象にする",
        default=True,
    )


# ShapeKeyのリネームを実行するオペレーター
class YWTA_OT_RenameShapeKeys(Operator):
    bl_idname = "ywta.rename_shape_keys"
    bl_label = "ShapeKey名を置換"
    bl_description = "ShapeKeyの名前を検索して置換します"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.shape_key_rename
        search = props.search_pattern
        replace = props.replace_pattern
        case_sensitive = props.case_sensitive
        selected_only = props.selected_only

        if not search:
            self.report({"ERROR"}, "検索パターンを入力してください")
            return {"CANCELLED"}

        # 処理対象のオブジェクトを取得
        objects = context.selected_objects if selected_only else bpy.data.objects

        # 変更されたShapeKeyの数をカウント
        renamed_count = 0
        affected_objects = 0

        for obj in objects:
            # メッシュオブジェクトでShapeKeyを持つもののみ処理
            if obj.type != "MESH" or not obj.data.shape_keys:
                continue

            shape_keys = obj.data.shape_keys.key_blocks
            obj_renamed = False

            for key in shape_keys:
                # 'Basis'は変更しない
                if key.name == "Basis":
                    continue

                # 検索パターンに一致するか確認
                if case_sensitive:
                    if search in key.name:
                        old_name = key.name
                        key.name = key.name.replace(search, replace)
                        renamed_count += 1
                        obj_renamed = True
                else:
                    # 大文字小文字を区別しない場合
                    lower_name = key.name.lower()
                    lower_search = search.lower()
                    if lower_search in lower_name:
                        # 元の大文字小文字を保持しながら置換
                        old_name = key.name
                        # 検索文字列の位置を特定
                        pos = lower_name.find(lower_search)
                        # 置換
                        new_name = key.name[:pos] + replace + key.name[pos + len(search) :]
                        key.name = new_name
                        renamed_count += 1
                        obj_renamed = True

            if obj_renamed:
                affected_objects += 1

        if renamed_count > 0:
            self.report(
                {"INFO"},
                f"{affected_objects}オブジェクトの{renamed_count}個のShapeKeyを置換しました",
            )
        else:
            self.report({"INFO"}, "一致するShapeKeyが見つかりませんでした")

        return {"FINISHED"}


# ShapeKeyリネーム用のUIパネル
class YWTA_PT_ShapeKeyRename(Panel):
    bl_label = "ShapeKey名の検索と置換"
    bl_idname = "YWTA_PT_shape_key_rename"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "YWTA"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        props = context.scene.shape_key_rename

        # 検索と置換のフィールド
        layout.prop(props, "search_pattern")
        layout.prop(props, "replace_pattern")

        # オプション
        box = layout.box()
        box.label(text="オプション:")
        box.prop(props, "case_sensitive")
        box.prop(props, "selected_only")

        # 実行ボタン
        layout.operator("ywta.rename_shape_keys")


# 登録するクラスのリスト
classes = [
    ShapeKeyRenameProperties,
    YWTA_OT_RenameShapeKeys,
    YWTA_PT_ShapeKeyRename,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.shape_key_rename = PointerProperty(type=ShapeKeyRenameProperties)


def unregister():
    del bpy.types.Scene.shape_key_rename
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
