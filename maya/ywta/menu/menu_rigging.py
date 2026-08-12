"""
リギングメニュー定義

リギング関連のメニュー項目を定義します。
"""

import maya.cmds as cmds


def create_rigging_menu(parent_menu):
    """リギングメニューを作成する

    Args:
        parent_menu: 親メニュー

    Returns:
        作成されたメニュー項目
    """
    rig_menu = cmds.menuItem(subMenu=True, tearOff=True, parent=parent_menu, label="Rigging")

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
        command="import ywta.rig.joint_edit_tools as oj; oj.JointEditToolsWindow()",
        image="orientJoint.png",
        annotation="ジョイントの向きを編集するためのツールを開きます",
    )

    cmds.menuItem(
        parent=rig_menu,
        label="Mirror Joint Hierarchy (Static YZ)",
        command="import ywta.rig.joint_mirror as joint_mirror; joint_mirror.mirror_selected_hierarchy()",
        annotation="side tokenと衝突を事前検証して選択joint階層を静的mirrorします",
    )

    cmds.menuItem(
        parent=rig_menu,
        label="Create Joint",
        command="import ywta.rig.create_joint as cj; cj.create_joint_from_selected_component()",
        image="joint.png",
        annotation="選択全体の中心、空選択では原点へjointを単一Undoで作成します",
    )

    create_menu = cmds.menuItem(
        parent=rig_menu,
        subMenu=True,
        tearOff=True,
        label="Create at Selection Center",
        annotation="選択全体の中心、空選択では原点へ基本objectを作成します",
    )
    for label, function in (
        ("Null", "create_null"),
        ("Locator", "create_locator"),
        ("Poly Cube", "create_cube"),
        ("Poly Sphere", "create_sphere"),
        ("Poly Cylinder", "create_cylinder"),
        ("Poly Plane", "create_plane"),
    ):
        cmds.menuItem(
            parent=create_menu,
            label=label,
            command="import ywta.rig.create_object as create_object; create_object.{}()".format(function),
        )

    constraint_menu = cmds.menuItem(
        parent=rig_menu,
        subMenu=True,
        tearOff=True,
        label="Constraints",
        annotation="driversを先、drivenを最後に選択してconstraintを作成します",
    )
    for label, kind in (
        ("Parent Constraint", "parent"),
        ("Point Constraint", "point"),
        ("Orient Constraint", "orient"),
        ("Scale Constraint", "scale"),
        ("Aim Constraint", "aim"),
    ):
        cmds.menuItem(
            parent=constraint_menu,
            label=label,
            command="import ywta.rig.constraint_tools as constraints; constraints.create_selected('{}')".format(kind),
        )
    cmds.menuItem(parent=constraint_menu, divider=True)
    cmds.menuItem(
        parent=constraint_menu,
        label="Delete Constraints",
        command="import ywta.rig.constraint_tools as constraints; constraints.delete_constraints()",
        annotation="選択transformを駆動するconstraintを単一Undoで削除します",
    )

    cmds.menuItem(
        parent=rig_menu,
        label="Name Tools",
        command="import ywta.name; ywta.name.show()",
        image="menuIconModify.png",
        imageOverlayLabel="name",
        annotation="選択ノードの連番、検索置換、prefix/suffix、番号を一括編集します",
    )

    cmds.menuItem(
        parent=rig_menu,
        label="Joint Size Tools",
        command="import ywta.rig.joint_size as js; js.set_joint_size_from_menu()",
        image="joint.png",
        annotation="ジョイントのサイズを階層で一括設定します",
    )

    cmds.menuItem(
        parent=rig_menu,
        label="Export Skeleton",
        command="import ywta.rig.skeleton_io as skeleton_io; skeleton_io.save_selected()",
        image="kinJoint.png",
        annotation="選択rootのスケルトン構造を検証可能なJSONへエクスポートします",
    )

    cmds.menuItem(
        parent=rig_menu,
        label="Import Skeleton",
        command="import ywta.rig.skeleton_io as skeleton_io; skeleton_io.load_dialog()",
        image="kinJoint.png",
        annotation="versioned JSONから衝突を拒否してスケルトンをインポートします",
    )

    cmds.menuItem(
        parent=rig_menu,
        label="Import Skeleton (Bake Rotate to Joint Orient)",
        command="import ywta.rig.skeleton_io as skeleton_io; skeleton_io.load_dialog(bake_to_joint_orient=True)",
        image="kinJoint.png",
        annotation="world姿勢を維持してrotateをjointOrientへ統合してインポートします",
    )

    cmds.menuItem(
        parent=rig_menu,
        label="Import Skeleton (Clean Joint TRS)",
        command="import ywta.rig.skeleton_io as skeleton_io; skeleton_io.load_dialog(bake_to_joint_orient=True, zero_joint_scales=True)",
        image="kinJoint.png",
        annotation="world位置・回転を維持し、rotateをjointOrientへ統合してjoint scaleを1にします",
    )

    cmds.menuItem(parent=rig_menu, divider=True, dividerLabel="Temporary Skeleton Clipboard")
    cmds.menuItem(
        parent=rig_menu,
        label="Save Temporary Skeleton",
        command="import ywta.rig.skeleton_io as skeleton_io; skeleton_io.save_temp_selected()",
        annotation="選択root hierarchyをMayaユーザー用の一時JSONへ保存します",
    )
    cmds.menuItem(
        parent=rig_menu,
        label="Load Temporary Skeleton",
        command="import ywta.rig.skeleton_io as skeleton_io; skeleton_io.load_temp_dialog()",
        annotation="一時Skeleton JSONを任意namespaceへ検証してインポートします",
    )
    cmds.menuItem(
        parent=rig_menu,
        label="Load Temporary Skeleton (Clean Joint TRS)",
        command="import ywta.rig.skeleton_io as skeleton_io; skeleton_io.load_temp_dialog(bake_to_joint_orient=True, zero_joint_scales=True)",
        annotation="一時Skeleton JSONをrotate 0・joint scale 1へbakeしてインポートします",
    )

    cmds.menuItem(parent=rig_menu, divider=True, dividerLabel="Selection Navigation")
    cmds.menuItem(
        parent=rig_menu,
        label="Select Child Joints",
        command="import ywta.rig.selection_tools as selection_tools; selection_tools.select_child_joints()",
        annotation="選択階層の子孫jointを選択します",
    )
    cmds.menuItem(
        parent=rig_menu,
        label="Select Child Meshes",
        command="import ywta.rig.selection_tools as selection_tools; selection_tools.select_child_meshes()",
        annotation="選択階層の表示mesh transformを選択します",
    )
    cmds.menuItem(
        parent=rig_menu,
        label="Select Influencing Joints",
        command="import ywta.rig.selection_tools as selection_tools; selection_tools.select_influencing_joints()",
        annotation="選択meshのskinCluster influence jointを選択します",
    )
    cmds.menuItem(
        parent=rig_menu,
        label="Select Influenced Meshes",
        command="import ywta.rig.selection_tools as selection_tools; selection_tools.select_influenced_meshes()",
        annotation="選択jointがinfluenceとして登録されたmeshを選択します",
    )
    cmds.menuItem(
        parent=rig_menu,
        label="Snap A to B (Position)",
        command="import ywta.rig.selection_tools as selection_tools; selection_tools.snap_to_last()",
        annotation="最後に選択したtransformのworld pivotへ他の選択を位置だけ合わせます",
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

    cmds.menuItem(
        parent=rig_menu,
        label="Swap Selected Control Shapes",
        command="import ywta.rig.control as control; control.swap_selected_curves()",
        annotation="transform接続とshape表示状態を維持して選択controlの形状を差し替えます",
    )

    cmds.menuItem(
        parent=rig_menu,
        label="Mirror Selected Control Shape",
        command="import ywta.rig.control as control; control.mirror_selected_control_shapes()",
        annotation="選択した片側control形状をworld YZ反転して反対側controlへ差し替えます",
    )

    cmds.menuItem(
        parent=rig_menu,
        label="Edit Selected Control CVs",
        command="import ywta.rig.control as control; control.select_control_cvs()",
        annotation="選択control直下にある全NURBS curve CVを編集選択します",
    )

    cmds.menuItem(
        parent=rig_menu,
        label="Combine Selected Control Shapes",
        command="import ywta.rig.control as control; control.combine_control_shapes()",
        annotation="最後のcontrolへworld形状を維持して結合し、他の選択controlを削除します",
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
