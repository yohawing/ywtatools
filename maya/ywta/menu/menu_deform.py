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
        image="menuIconSkinning.png",
        annotation="複数選択はvirtual結合し、1つの検証可能なSkin JSONへ保存します",
    )

    cmds.menuItem(
        parent=deform_menu,
        label="Load Skin Weights (Same Topology)",
        command="import ywta.deform.skin_io as skin_io; skin_io.load_selected()",
        image="menuIconSkinning.png",
        annotation="同一トポロジーの選択メッシュへスキンウェイトを復元します",
    )

    cmds.menuItem(
        parent=deform_menu,
        label="Load Skin Weights to Selected Vertices",
        command="import ywta.deform.skin_io as skin_io; skin_io.load_selected_subset()",
        image="menuIconSkinning.png",
        annotation="同一トポロジーJSONから選択頂点だけのウェイトを復元します",
    )

    cmds.menuItem(
        parent=deform_menu,
        label="Transfer Skin Weights (Configured)",
        command="import ywta.deform.skin_io as skin_io; skin_io.load_selected_transfer()",
        image="menuIconCopy.png",
        annotation="保存sourceを再構築して設定済みsurface associationで転送します",
    )
    cmds.menuItem(
        parent=deform_menu,
        label="Skin Transfer Options...",
        command="import ywta.deform.skin_io as skin_io; skin_io.show_transfer_options()",
        image="menuIconOptions.png",
        annotation="closestPoint / rayCast / closestComponentを設定します",
    )

    cmds.menuItem(parent=deform_menu, divider=True, dividerLabel="Temporary Skin Clipboard")
    cmds.menuItem(
        parent=deform_menu,
        label="Save Temporary Skin Weights",
        command="import ywta.deform.skin_io as skin_io; skin_io.save_temp_selected()",
        image="menuIconFile.png",
        annotation="複数選択はvirtual結合し、Mayaユーザー用の一時JSONへ保存します",
    )
    cmds.menuItem(
        parent=deform_menu,
        label="Load Temporary Skin Weights (Direct)",
        command="import ywta.deform.skin_io as skin_io; skin_io.load_temp_selected()",
        image="menuIconFile.png",
        annotation="一時JSONを同一トポロジーの選択meshへ復元します",
    )
    cmds.menuItem(
        parent=deform_menu,
        label="Transfer Temporary Skin Weights (Configured)",
        command="import ywta.deform.skin_io as skin_io; skin_io.load_temp_selected(transfer_mode=True)",
        image="menuIconCopy.png",
        annotation="一時JSONを異なるトポロジーの選択meshへ設定済み方式で転送します",
    )

    cmds.menuItem(parent=deform_menu, divider=True, dividerLabel="Vertex Weights")
    cmds.menuItem(
        parent=deform_menu,
        label="Copy Vertex Weights",
        command="import ywta.deform.skin_weights as skin_weights; skin_weights.copy_selected_vertex_weights()",
        image="menuIconCopy.png",
        annotation="選択した1頂点のスキンウェイトを永続clipboardへコピーします",
    )
    cmds.menuItem(
        parent=deform_menu,
        label="Copy Average Vertex Weights",
        command="import ywta.deform.skin_weights as skin_weights; skin_weights.copy_average_vertex_weights()",
        image="menuIconCopy.png",
        annotation="選択した複数頂点の平均ウェイトを永続clipboardへコピーします",
    )
    cmds.menuItem(
        parent=deform_menu,
        label="Paste Vertex Weights",
        command="import ywta.deform.skin_weights as skin_weights; skin_weights.paste_vertex_weights()",
        image="menuIconEdit.png",
        annotation="コピー済みスキンウェイトを選択頂点へ一括Undoで貼り付けます",
    )
    cmds.menuItem(
        parent=deform_menu,
        label="Average Vertex Weights",
        command="import ywta.deform.skin_weights as skin_weights; skin_weights.average_vertex_weights()",
        image="menuIconModify.png",
        annotation="選択頂点のスキンウェイトを平均して全選択頂点へ適用します",
    )
    cmds.menuItem(
        parent=deform_menu,
        label="Add Selected Skin Influences",
        command="import ywta.deform.skin_influences as influences; influences.add_selected_influences()",
        image="menuIconAdd.png",
        annotation="選択jointを選択meshへ既存ウェイトを変えずweight 0で追加します",
    )
    cmds.menuItem(
        parent=deform_menu,
        label="Remove Selected Unused Influences",
        command="import ywta.deform.skin_influences as influences; influences.remove_selected_influences()",
        image="menuIconReset.png",
        annotation="選択jointが未使用かつunlockedの場合だけ選択meshから削除します",
    )
    cmds.menuItem(
        parent=deform_menu,
        label="Mirror Skin Weights +X to -X",
        command="import ywta.deform.skin_mirror as skin_mirror; skin_mirror.mirror_selected_positive_to_negative()",
        image="menuIconEdit.png",
        annotation="選択meshのウェイトをworld YZ面で+Xから-Xへミラーします",
    )
    cmds.menuItem(
        parent=deform_menu,
        label="Mirror Skin Weights -X to +X",
        command="import ywta.deform.skin_mirror as skin_mirror; skin_mirror.mirror_selected_negative_to_positive()",
        image="menuIconEdit.png",
        annotation="選択meshのウェイトをworld YZ面で-Xから+Xへミラーします",
    )
    smooth_item = cmds.menuItem(
        parent=deform_menu,
        label="Smooth Selected Skin Weights",
        command="import ywta.deform.skin_smooth as skin_smooth; skin_smooth.smooth_selected()",
        image="menuIconModify.png",
        annotation="保存済み設定で選択componentを隣接頂点平均へsmoothingします",
    )
    cmds.menuItem(
        parent=deform_menu,
        insertAfter=smooth_item,
        optionBox=True,
        command="import ywta.deform.skin_smooth as skin_smooth; skin_smooth.show_options()",
        image="menuIconOptions.png",
        annotation="Skin Smoothのstrengthとiterationsを設定します",
    )
    cleanup_item = cmds.menuItem(
        parent=deform_menu,
        label="Remove Unused Skin Influences",
        command="import ywta.deform.influence_cleanup as cleanup; cleanup.remove_unused_selected()",
        image="menuIconReset.png",
        annotation="全出力meshで未使用のunlocked influenceだけを単一Undoで削除します",
    )
    cmds.menuItem(
        parent=deform_menu,
        insertAfter=cleanup_item,
        optionBox=True,
        command="import ywta.deform.influence_cleanup as cleanup; cleanup.show_options()",
        image="menuIconOptions.png",
        annotation="未使用判定thresholdとlocked influence保護を設定します",
    )
    cmds.menuItem(
        parent=deform_menu,
        label="Combine Skinned Meshes",
        command="import ywta.deform.combine_skinned as combine_skinned; combine_skinned.combine_selected()",
        image="menuIconConnect.png",
        annotation="元meshを残し、頂点順を検証して正確なウェイト付きで結合します",
    )
    cmds.menuItem(
        parent=deform_menu,
        label="Separate Skinned Mesh Shells",
        command="import ywta.deform.separate_skinned as separate_skinned; separate_skinned.separate_selected()",
        image="menuIconEdit.png",
        annotation="元meshを残し、vertex mappingで各shellを正確なウェイト付きmeshへ分割します",
    )

    transfer_shape_menu_item = cmds.menuItem(
        parent=deform_menu,
        label="Transfer Shape",
        command="import ywta.deform.transfer_shape as tbs;tbs.exec_from_menu()",
        image="falloff_transfer.png",
        annotation="選択したsource・targetの2メッシュ間で頂点シェイプを転送します（sourceを先、targetを後に選択）",
    )

    cmds.menuItem(
        parent=deform_menu,
        insertAfter=transfer_shape_menu_item,
        optionBox=True,
        command="import ywta.deform.transfer_shape as tbs; tbs.display_menu_options()",
        image="menuIconOptions.png",
        annotation="2メッシュ間のシェイプ転送でColor Set使用とBlendShape target追加を設定します",
    )

    cmds.menuItem(
        parent=deform_menu,
        label="Duplicate Skinned Mesh",
        command="import ywta.rig.skin_duplicate as sd; sd.duplicate_skinned_mesh()",
        image="menuIconCopy.png",
        annotation="選択したスキン済みメッシュを複製し、ウェイトを保持して元名へ置換します",
    )

    # デフォーマー関連
    cmds.menuItem(
        parent=deform_menu,
        label="Bake Deformer to Blendshape",
        command="import ywta.deform.deformer as bd; bd.bake_deformed_to_blendshape()",
        image="menuIconDeformations.png",
        annotation="選択メッシュをplayback範囲の各フレームへBlendShape targetとしてベイクします（2つ選択時は先をsource、後をtarget）",
    )

    cmds.menuItem(
        parent=deform_menu,
        label="Set Keyframe Blendshape Per Frame",
        command="import ywta.deform.deformer as bd; bd.set_keyframe_blendshape_per_frame()",
        image="menuIconKeys.png",
        annotation="選択メッシュの既存BlendShape targetをplayback範囲の1フレームずつへキー設定します",
    )

    # ブレンドシェイプ関連
    cmds.menuItem(parent=deform_menu, divider=True, dividerLabel="BlendShape")

    cmds.menuItem(
        parent=deform_menu,
        label="BlendShape Target Renamer",
        command="import ywta.deform.target_renamer as tr; tr.show_blendshape_target_renamer()",
        image="menuIconModify.png",
        annotation="選択または指定したBlendShape nodeのtarget名を検索置換するUIを開きます",
    )

    return deform_menu
