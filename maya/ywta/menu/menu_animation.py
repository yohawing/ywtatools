"""
アニメーションメニュー定義

アニメーション関連のメニュー項目を定義します。
"""

import maya.cmds as cmds
import maya.mel as mel


def create_animation_menu(parent_menu):
    """アニメーションメニューを作成する

    Args:
        parent_menu: 親メニュー

    Returns:
        作成されたメニュー項目
    """
    animation_menu = cmds.menuItem(
        subMenu=True, tearOff=True, parent=parent_menu, label="Animation"
    )

    # アニメーション関連のメニュー項目を追加
    # 現在は空のメニューですが、将来的にはここにアニメーション関連の機能を追加します

    return animation_menu
