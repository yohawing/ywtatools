"""
デフォームメニュー定義

デフォーメーション関連のメニュー項目を定義します。
"""

import maya.cmds as cmds
import maya.mel as mel


def create_deform_menu(parent_menu):
    """デフォームメニューを作成する

    Args:
        parent_menu: 親メニュー

    Returns:
        作成されたメニュー項目
    """
    deform_menu = cmds.menuItem(
        subMenu=True, tearOff=True, parent=parent_menu, label="Deform"
    )

    # スキニング関連
    cmds.menuItem(parent=deform_menu, divider=True, dividerLabel="Skinning")

    transfer_shape_menu_item = cmds.menuItem(
        parent=deform_menu,
        label="Transfer Shape",
        command="import ywta.deform.transfer_shape as tbs;tbs.exec_from_menu()",
        image="exportSmoothSkin.png",
        annotation="シェイプを別のメッシュに転送します",
    )

    cmds.menuItem(
        parent=deform_menu,
        insertAfter=transfer_shape_menu_item,
        optionBox=True,
        command="import ywta.deform.transfer_shape as tbs; tbs.display_menu_options()",
        annotation="シェイプ転送のオプションを設定します",
    )

    cmds.menuItem(
        parent=deform_menu,
        label="Duplicate Skinned Mesh",
        command="import ywta.rig.skin_duplicate as sd; sd.duplicate_skinned_mesh()",
        annotation="スキンが適用されたメッシュを複製します",
    )

    cmds.menuItem(
        parent=deform_menu,
        label="Export Skin Weights",
        command="import ywta.deform.skinio as skinio; skinio.export_skin()",
        annotation="スキンウェイトをエクスポートします",
    )

    cmds.menuItem(
        parent=deform_menu,
        label="Import Skin Weights",
        command="import ywta.deform.skinio as skinio; skinio.import_skin(to_selected_shapes=True)",
        image="importSmoothSkin.png",
        annotation="スキンウェイトをインポートします",
    )

    # デフォーマー関連
    cmds.menuItem(
        parent=deform_menu,
        label="Bake Deformer to Blendshape",
        command="import ywta.deform.deformer as bd; bd.bake_deformed_to_blendshape()",
        annotation="デフォーマーの効果をブレンドシェイプにベイクします",
    )

    cmds.menuItem(
        parent=deform_menu,
        label="Set Keyframe Blendshape Per Frame",
        command="import ywta.deform.deformer as bd; bd.set_keyframe_blendshape_per_frame()",
        annotation="フレームごとにブレンドシェイプのキーフレームを設定します",
    )

    # ブレンドシェイプ関連
    cmds.menuItem(parent=deform_menu, divider=True, dividerLabel="BlendShape")

    cmds.menuItem(
        parent=deform_menu,
        label="BlendShape Target Renamer",
        command="import ywta.deform.target_renamer as tr; tr.show_blendshape_target_renamer()",
        image="blendShape.png",
        annotation="ブレンドシェイプターゲットの名前を変更するツールを開きます",
    )

    return deform_menu
