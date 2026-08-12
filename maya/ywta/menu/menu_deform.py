"""
デフォームメニュー定義

デフォーメーション関連のメニュー項目を定義します。
"""

import maya.cmds as cmds


def create_deform_menu(parent_menu):
    """デフォームメニューを作成する

    Args:
        parent_menu: 親メニュー

    Returns:
        作成されたメニュー項目
    """
    deform_menu = cmds.menuItem(subMenu=True, tearOff=True, parent=parent_menu, label="Deform")

    # スキニング関連
    cmds.menuItem(parent=deform_menu, divider=True, dividerLabel="Skinning")

    cmds.menuItem(
        parent=deform_menu,
        label="Save Skin Weights",
        command="import ywta.deform.skin_io as skin_io; skin_io.save_selected()",
        image="exportSmoothSkin.png",
        annotation="選択メッシュのスキンウェイトを検証可能なJSONへ保存します",
    )

    cmds.menuItem(
        parent=deform_menu,
        label="Load Skin Weights (Same Topology)",
        command="import ywta.deform.skin_io as skin_io; skin_io.load_selected()",
        image="smoothSkin.png",
        annotation="同一トポロジーの選択メッシュへスキンウェイトを復元します",
    )

    cmds.menuItem(
        parent=deform_menu,
        label="Transfer Skin Weights (Closest Point)",
        command="import ywta.deform.skin_io as skin_io; skin_io.load_selected_transfer()",
        image="copySkinWeight.png",
        annotation="保存sourceを再構築して異なるトポロジーへスキンウェイトを転送します",
    )

    cmds.menuItem(parent=deform_menu, divider=True, dividerLabel="Vertex Weights")
    cmds.menuItem(
        parent=deform_menu,
        label="Copy Vertex Weights",
        command="import ywta.deform.skin_weights as skin_weights; skin_weights.copy_selected_vertex_weights()",
        annotation="選択した1頂点のスキンウェイトをprocess内clipboardへコピーします",
    )
    cmds.menuItem(
        parent=deform_menu,
        label="Paste Vertex Weights",
        command="import ywta.deform.skin_weights as skin_weights; skin_weights.paste_vertex_weights()",
        annotation="コピー済みスキンウェイトを選択頂点へ一括Undoで貼り付けます",
    )
    cmds.menuItem(
        parent=deform_menu,
        label="Average Vertex Weights",
        command="import ywta.deform.skin_weights as skin_weights; skin_weights.average_vertex_weights()",
        annotation="選択頂点のスキンウェイトを平均して全選択頂点へ適用します",
    )
    cmds.menuItem(
        parent=deform_menu,
        label="Remove Unused Skin Influences",
        command="import ywta.deform.influence_cleanup as cleanup; cleanup.remove_unused_selected()",
        annotation="全出力meshで未使用のunlocked influenceだけを単一Undoで削除します",
    )
    cmds.menuItem(
        parent=deform_menu,
        label="Combine Skinned Meshes",
        command="import ywta.deform.combine_skinned as combine_skinned; combine_skinned.combine_selected()",
        annotation="元meshを残し、頂点順を検証して正確なウェイト付きで結合します",
    )

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
