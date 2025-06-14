"""
リギングメニュー定義

リギング関連のメニュー項目を定義します。
"""

import maya.cmds as cmds
import maya.mel as mel


def create_rigging_menu(parent_menu):
    """リギングメニューを作成する

    Args:
        parent_menu: 親メニュー

    Returns:
        作成されたメニュー項目
    """
    rig_menu = cmds.menuItem(
        subMenu=True, tearOff=True, parent=parent_menu, label="Rigging"
    )

    # 共通機能
    cmds.menuItem(
        parent=rig_menu,
        label="Freeze to offsetParentMatrix",
        command="import ywta.rig.common; ywta.rig.common.freeze_to_parent_offset()",
        annotation="トランスフォーム値をoffsetParentMatrixに転送します",
    )

    # スケルトン関連
    cmds.menuItem(parent=rig_menu, divider=True, dividerLabel="Skeleton")

    cmds.menuItem(
        parent=rig_menu,
        label="Joint Edit Tools",
        command="import ywta.rig.orientjoints as oj; oj.OrientJointsWindow()",
        image="orientJoint.png",
        annotation="ジョイントの向きを編集するためのツールを開きます",
    )

    cmds.menuItem(
        parent=rig_menu,
        label="Create Joint",
        command="import ywta.rig.create_joint as cj; cj.create_joint_from_selected_component()",
        image="joint.png",
        annotation="選択されたコンポーネントからジョイントを作成します",
    )

    cmds.menuItem(
        parent=rig_menu,
        label="Rename Chain",
        command="import ywta.name; ywta.name.rename_chain_ui()",
        image="menuIconModify.png",
        imageOverlayLabel="name",
        annotation="ジョイントチェーンの名前を一括変更します",
    )

    cmds.menuItem(
        parent=rig_menu,
        label="Export Skeleton",
        command="import ywta.rig.skeleton as skeleton; skeleton.dump()",
        image="kinJoint.png",
        annotation="スケルトン構造をファイルにエクスポートします",
    )

    cmds.menuItem(
        parent=rig_menu,
        label="Import Skeleton",
        command="import ywta.rig.skeleton as skeleton; skeleton.load()",
        image="kinJoint.png",
        annotation="スケルトン構造をファイルからインポートします",
    )

    item = cmds.menuItem(
        parent=rig_menu,
        label="Connect Twist Joint",
        command="import ywta.rig.swingtwist as st; st.create_from_menu()",
        annotation="ツイストジョイントを接続します",
    )

    cmds.menuItem(
        parent=rig_menu,
        insertAfter=item,
        optionBox=True,
        command="import ywta.rig.swingtwist as st; st.display_menu_options()",
        annotation="ツイストジョイント接続のオプションを設定します",
    )

    # アニメーションリグ関連
    cmds.menuItem(parent=rig_menu, divider=True, dividerLabel="Animation Rig")

    cmds.menuItem(
        parent=rig_menu,
        label="Control Creator",
        command="import ywta.rig.control_ui as control_ui; control_ui.show()",
        image="orientJoint.png",
        annotation="コントロールカーブを作成するツールを開きます",
    )

    cmds.menuItem(
        parent=rig_menu,
        label="Export Selected Control Curves",
        command="import ywta.rig.control as control; control.export_curves()",
        annotation="選択したコントロールカーブをエクスポートします",
    )

    cmds.menuItem(
        parent=rig_menu,
        label="Import Control Curves",
        command="import ywta.rig.control as control; control.import_curves()",
        annotation="コントロールカーブをインポートします",
    )

    # HumanIK関連
    cmds.menuItem(parent=rig_menu, divider=True, dividerLabel="HumanIK")

    cmds.menuItem(
        parent=rig_menu,
        label="HumanIK Auto Setup",
        command="import ywta.rig.humanik as humanik; humanik.setup_hik_character()",
        annotation="HumanIKキャラクターを自動セットアップします",
    )

    return rig_menu
