"""
ユーティリティメニュー定義

ユーティリティ関連のメニュー項目を定義します。
"""

import maya.cmds as cmds
import maya.mel as mel


def create_utility_menu(parent_menu):
    """ユーティリティメニューを作成する

    Args:
        parent_menu: 親メニュー

    Returns:
        作成されたメニュー項目
    """
    utility_menu = cmds.menuItem(
        subMenu=True, tearOff=True, parent=parent_menu, label="Utility"
    )

    # テスト・開発関連
    cmds.menuItem(parent=utility_menu, divider=True, dividerLabel="Test")
    cmds.menuItem(
        parent=utility_menu,
        label="Unit Test Runner",
        command="import ywta.test.maya_unit_test_ui; ywta.test.maya_unit_test_ui.show()",
        imageOverlayLabel="Test",
        annotation="ユニットテストを実行するためのUIを開きます",
    )

    # 開発ツール
    cmds.menuItem(parent=utility_menu, divider=True, dividerLabel="Development")

    cmds.menuItem(
        parent=utility_menu,
        label="Dependency Visualizer",
        command="import ywta.utility.dependency_visualizer as dv; dv.show()",
        annotation="モジュール間の依存関係を分析・可視化します",
    )

    cmds.menuItem(
        parent=utility_menu,
        label="Dependencies Analyzer CLI",
        command="import maya.cmds as cmds; cmds.confirmDialog(title='依存関係分析', message='コマンドラインから実行するには:\\n\\nimport ywta.utility.dependency_analyzer as analyzer\\n\\n# 依存関係の分析\\ndependencies = analyzer.analyze_dependencies()\\n\\n# 依存関係グラフの生成\\nanalyzer.generate_dependency_graph(dependencies, \"dependencies.dot\")\\n\\n# 循環依存の検出\\ncycles = analyzer.detect_cycles(dependencies)\\n\\n# __init__.pyファイルの更新\\nanalyzer.update_init_files(dependencies)', button=['OK'])",
        annotation="依存関係分析ツールのコマンドライン使用方法を表示します",
    )

    cmds.menuItem(
        parent=utility_menu,
        label="Reload All Modules",
        command="import ywta.reloadmodules; ywta.reloadmodules.reload_modules()",
        imageOverlayLabel="Test",
        annotation="すべてのモジュールをリロードします",
    )

    cmds.menuItem(
        parent=utility_menu,
        label="Resource Browser",
        command="import maya.app.general.resourceBrowser as rb; rb.resourceBrowser().run()",
        imageOverlayLabel="name",
        annotation="Mayaのリソースブラウザを開きます",
    )

    return utility_menu
