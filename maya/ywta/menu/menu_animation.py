"""
アニメーションメニュー定義

アニメーション関連のメニュー項目を定義します。
"""

import maya.cmds as cmds

import ywta.link.camera_ui as camera_ui
import ywta.link.playback_ui as playback_ui


def create_animation_menu(parent_menu):
    """アニメーションメニューを作成する

    Args:
        parent_menu: 親メニュー

    Returns:
        作成されたメニュー項目
    """
    animation_menu = cmds.menuItem(subMenu=True, tearOff=True, parent=parent_menu, label="Animation")

    cmds.menuItem(
        parent=animation_menu,
        label="Selection Sets",
        image="menuIconSelected.png",
        command="import ywta.anim.selection_sets as selection_sets; selection_sets.show()",
        annotation="control selection setsを作成・選択・portable JSON移送します",
    )

    cmds.menuItem(parent=animation_menu, divider=True, dividerLabel="Pose")
    cmds.menuItem(
        parent=animation_menu,
        label="Set Pose ID...",
        image="createPose.png",
        command="import ywta.anim.pose_io as pose_io; pose_io.set_pose_id_selected()",
        annotation="選択controlへ改名後も安定する明示Pose IDを設定します",
    )
    cmds.menuItem(
        parent=animation_menu,
        label="Save Selected Pose",
        image="fileSave.png",
        command="import ywta.anim.pose_io as pose_io; pose_io.save_selected()",
        annotation="選択コントロールのポーズをnamespace可搬JSONへ保存します",
    )
    load_pose_item = cmds.menuItem(
        parent=animation_menu,
        label="Load Pose",
        image="fileOpen.png",
        command="import ywta.anim.pose_io as pose_io; pose_io.load_pose_with_settings()",
        annotation="保存済みBlend/Selected-only設定でポーズを適用します",
    )
    cmds.menuItem(
        parent=animation_menu,
        insertAfter=load_pose_item,
        optionBox=True,
        image="menuIconOptions.png",
        command="import ywta.anim.pose_io as pose_io; pose_io.show_load_options()",
        annotation="PoseのBlendと選択control限定を設定します",
    )
    cmds.menuItem(
        parent=animation_menu,
        label="Load Pose to Selected",
        image="fileOpen.png",
        command="import ywta.anim.pose_io as pose_io; pose_io.load_pose(selected_only=True, blend=pose_io.get_load_settings()[0])",
        annotation="保存済みBlendで現在選択中のコントロールだけへ適用します",
    )
    cmds.menuItem(
        parent=animation_menu,
        label="Save Temporary Pose",
        image="fileSave.png",
        command="import ywta.anim.pose_io as pose_io; pose_io.save_temp_selected()",
        annotation="選択controlをMayaユーザー用の一時Pose JSONへ保存します",
    )
    cmds.menuItem(
        parent=animation_menu,
        label="Load Temporary Pose (Configured)",
        image="fileOpen.png",
        command="import ywta.anim.pose_io as pose_io; pose_io.load_temp_with_settings()",
        annotation="保存済みBlend/Selected-only設定で一時Poseを適用します",
    )

    cmds.menuItem(parent=animation_menu, divider=True, dividerLabel="Animation Clip")
    cmds.menuItem(
        parent=animation_menu,
        label="Save Selected Animation Clip",
        image="fileSave.png",
        command="import ywta.anim.clip_io as clip_io; clip_io.save_selected()",
        annotation="選択コントロールのhighlight/playback rangeキーを可搬JSONへ保存します",
    )
    configured_clip_item = cmds.menuItem(
        parent=animation_menu,
        label="Load Animation Clip (Configured)",
        image="fileOpen.png",
        command="import ywta.anim.clip_io as clip_io; clip_io.load_clip_with_settings()",
        annotation="保存済みMode/Selected-only設定でclipを適用します",
    )
    cmds.menuItem(
        parent=animation_menu,
        insertAfter=configured_clip_item,
        optionBox=True,
        image="menuIconOptions.png",
        command="import ywta.anim.clip_io as clip_io; clip_io.show_load_options()",
        annotation="Animation ClipのModeと選択control限定を設定します",
    )
    cmds.menuItem(
        parent=animation_menu,
        label="Load Animation Clip (Replace)",
        image="fileOpen.png",
        command="import ywta.anim.clip_io as clip_io; clip_io.load_clip(mode='replace')",
        annotation="現在フレームからclip範囲のキーを置換します",
    )
    cmds.menuItem(
        parent=animation_menu,
        label="Load Animation Clip (Place)",
        image="fileOpen.png",
        command="import ywta.anim.clip_io as clip_io; clip_io.load_clip(mode='place')",
        annotation="既存キー範囲を削除せず現在フレームからclipを配置します",
    )
    cmds.menuItem(
        parent=animation_menu,
        label="Load Animation Clip (Insert)",
        image="insertKeySmall.png",
        command="import ywta.anim.clip_io as clip_io; clip_io.load_clip(mode='insert')",
        annotation="対象controlの後続キーをずらしてclipを挿入します",
    )
    cmds.menuItem(
        parent=animation_menu,
        label="Load Animation Clip to Selected (Replace)",
        image="fileOpen.png",
        command="import ywta.anim.clip_io as clip_io; clip_io.load_clip(selected_only=True, mode='replace')",
        annotation="clipを現在フレームから選択コントロールだけへ置換適用します",
    )
    cmds.menuItem(
        parent=animation_menu,
        label="Save Temporary Animation Clip",
        image="fileSave.png",
        command="import ywta.anim.clip_io as clip_io; clip_io.save_temp_selected()",
        annotation="選択controlのhighlight/playback rangeをMayaユーザー用の一時Clip JSONへ保存します",
    )
    cmds.menuItem(
        parent=animation_menu,
        label="Load Temporary Animation Clip (Configured)",
        image="fileOpen.png",
        command="import ywta.anim.clip_io as clip_io; clip_io.load_temp_with_settings()",
        annotation="保存済みMode/Selected-only/anchor設定で一時Clipを適用します",
    )

    playback_ui.create_menu_item(animation_menu)
    camera_ui.create_menu_item(animation_menu)

    return animation_menu
