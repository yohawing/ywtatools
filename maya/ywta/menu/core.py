"""
メニューコア機能

YWTAツールのメインメニュー作成・管理機能を提供します。
"""

import webbrowser
import maya.cmds as cmds
import maya.mel as mel
from ywta.settings import DOCUMENTATION_ROOT

# メニューカテゴリモジュールをインポート
from ywta.menu import menu_animation
from ywta.menu import menu_mesh
from ywta.menu import menu_rigging
from ywta.menu import menu_deform
from ywta.menu import menu_utility


def create_menu():
    """YWTAメニューを作成します。"""
    # 既存のメニューがある場合は削除
    delete_menu()

    # メインメニューを作成
    gmainwindow = mel.eval("$tmp = $gMainWindow;")
    menu = cmds.menu("YWTA", parent=gmainwindow, tearOff=True, label="YWTA")

    # リロードメニュー項目
    cmds.menuItem(
        parent=menu,
        label="Reload YWTA",
        command="import ywta.reloadmodules; ywta.reloadmodules.unload_packages()",
        imageOverlayLabel="Test",
        annotation="YWTAツールをリロードします",
    )

    # 各カテゴリメニューを作成
    menu_animation.create_animation_menu(menu)
    menu_mesh.create_mesh_menu(menu)
    menu_rigging.create_rigging_menu(menu)
    menu_deform.create_deform_menu(menu)
    menu_utility.create_utility_menu(menu)

    # その他のトップレベルメニュー項目

    cmds.menuItem(
        parent=menu,
        label="Run Script",
        command="import ywta.pipeline.runscript; ywta.pipeline.runscript.show()",
        annotation="スクリプト実行ツールを開きます",
    )

    # Aboutセクション
    cmds.menuItem(parent=menu, divider=True)

    cmds.menuItem(
        parent=menu,
        label="Documentation",
        command="import ywta.menu; ywta.menu.documentation()",
        image="menuIconHelp.png",
        annotation="ドキュメントを開きます",
    )


def delete_menu():
    """YWTAメニューを削除します。"""
    # メニューが存在するか確認
    if cmds.menu("YWTA", exists=True):
        cmds.deleteUI("YWTA", menu=True)


def documentation():
    """ドキュメントのWebページを開きます。"""
    print("Opening documentation at:", DOCUMENTATION_ROOT)
    # ドキュメントのURLを開く
    webbrowser.open(DOCUMENTATION_ROOT)
