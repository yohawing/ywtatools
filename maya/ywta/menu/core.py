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

    cmds.menuItem(
        parent=menu,
        label="Batch Runner",
        command="import ywta.pipeline.batch_runner as batch_runner; batch_runner.show()",
        annotation="sceneごとに独立mayapyでPython処理と明示的な上書き保存を実行します",
    )

    cmds.menuItem(parent=menu, divider=True, dividerLabel="Export")
    cmds.menuItem(
        parent=menu,
        label="Export Selected FBX",
        command="import ywta.io.fbx_exporter as fbx_exporter; fbx_exporter.export_selected()",
        annotation="選択nodeをscene非破壊・設定復元・原子的置換でFBX exportします",
    )
    cmds.menuItem(
        parent=menu,
        label="Export Animation FBX",
        command="import ywta.io.fbx_exporter as fbx_exporter; fbx_exporter.export_animation()",
        annotation="選択root jointのhighlight/playback range animationをFBX exportします",
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
