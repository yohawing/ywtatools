"""
アニメーションメニュー定義

アニメーション関連のメニュー項目を定義します。
"""

import maya.cmds as cmds


def create_animation_menu(parent_menu):
    """アニメーションメニューを作成する

    Args:
        parent_menu: 親メニュー

    Returns:
        作成されたメニュー項目
    """
    animation_menu = cmds.menuItem(subMenu=True, tearOff=True, parent=parent_menu, label="Animation")

    cmds.menuItem(parent=animation_menu, divider=True, dividerLabel="Pose")
    cmds.menuItem(
        parent=animation_menu,
        label="Save Selected Pose",
        command="import ywta.anim.pose_io as pose_io; pose_io.save_selected()",
        annotation="選択コントロールのポーズをnamespace可搬JSONへ保存します",
    )
    cmds.menuItem(
        parent=animation_menu,
        label="Load Pose",
        command="import ywta.anim.pose_io as pose_io; pose_io.load_pose()",
        annotation="ポーズをscene内の一意に一致するコントロールへ適用します",
    )
    cmds.menuItem(
        parent=animation_menu,
        label="Load Pose to Selected",
        command="import ywta.anim.pose_io as pose_io; pose_io.load_pose(selected_only=True)",
        annotation="ポーズを現在選択中のコントロールだけへ適用します",
    )

    cmds.menuItem(parent=animation_menu, divider=True, dividerLabel="Animation Clip")
    cmds.menuItem(
        parent=animation_menu,
        label="Save Selected Animation Clip",
        command="import ywta.anim.clip_io as clip_io; clip_io.save_selected()",
        annotation="選択コントロールのplayback rangeキーを可搬JSONへ保存します",
    )
    cmds.menuItem(
        parent=animation_menu,
        label="Load Animation Clip",
        command="import ywta.anim.clip_io as clip_io; clip_io.load_clip()",
        annotation="clipを現在フレームからscene内の一致するコントロールへ適用します",
    )
    cmds.menuItem(
        parent=animation_menu,
        label="Load Animation Clip to Selected",
        command="import ywta.anim.clip_io as clip_io; clip_io.load_clip(selected_only=True)",
        annotation="clipを現在フレームから選択コントロールだけへ適用します",
    )

    return animation_menu
