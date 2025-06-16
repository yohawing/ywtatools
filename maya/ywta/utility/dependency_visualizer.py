"""
依存関係分析ツール

このモジュールは、YWTAプロジェクト内のモジュール間の依存関係を分析するための
ユーザーインターフェースを提供します。

使用方法:
    # Mayaから実行
    import ywta.utility.dependency_visualizer as visualizer
    visualizer.show()
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os
import sys
import logging
from functools import partial

try:
    from PySide6.QtCore import *
    from PySide6.QtGui import *
    from PySide6.QtWidgets import *
except ImportError:
    from PySide2.QtCore import *
    from PySide2.QtGui import *
    from PySide2.QtWidgets import *

from maya.app.general.mayaMixin import MayaQWidgetBaseMixin
import maya.cmds as cmds

import ywta.utility.dependency_analyzer as analyzer
import ywta.shortcuts as shortcuts

logger = logging.getLogger(__name__)


class DependencyVisualizerWindow(MayaQWidgetBaseMixin, QDialog):
    """依存関係分析ツールのメインウィンドウ"""

    _window_instance = None

    @classmethod
    def show_window(cls):
        if not cls._window_instance:
            cls._window_instance = cls()
        cls._window_instance.show()
        cls._window_instance.raise_()
        cls._window_instance.activateWindow()

    def __init__(self, parent=None):
        super(DependencyVisualizerWindow, self).__init__(parent)
        self.setWindowTitle("YWTA 依存関係分析ツール")
        self.setObjectName("ywtaDependencyVisualizerUI")
        self.setMinimumWidth(600)
        self.setMinimumHeight(400)

        self.dependencies = None
        self.cycles = None

        self.create_ui()

    def create_ui(self):
        """UIの作成"""
        main_layout = QVBoxLayout(self)

        # 分析タブ
        analysis_layout = main_layout

        # 分析オプション
        options_group = QGroupBox("分析オプション")
        options_layout = QVBoxLayout(options_group)
        analysis_layout.addWidget(options_group)

        # モジュールフィルタ
        filter_layout = QHBoxLayout()
        options_layout.addLayout(filter_layout)
        filter_layout.addWidget(QLabel("モジュールフィルタ:"))
        self.module_filter = QLineEdit()
        self.module_filter.setPlaceholderText("例: ywta.rig (空白で全モジュール)")
        filter_layout.addWidget(self.module_filter)

        # 分析ボタン
        analyze_button = QPushButton("依存関係を分析")
        analyze_button.clicked.connect(self.analyze_dependencies)
        options_layout.addWidget(analyze_button)

        # 結果表示エリア
        results_group = QGroupBox("分析結果")
        results_layout = QVBoxLayout(results_group)
        analysis_layout.addWidget(results_group)

        # 依存関係ツリー
        self.dependency_tree = QTreeWidget()
        self.dependency_tree.setHeaderLabels(["モジュール", "依存モジュール数"])
        self.dependency_tree.setAlternatingRowColors(True)
        results_layout.addWidget(self.dependency_tree)

        # 循環依存検出結果
        cycles_layout = QHBoxLayout()
        results_layout.addLayout(cycles_layout)
        cycles_layout.addWidget(QLabel("循環依存:"))
        self.cycles_label = QLabel("未検出")
        cycles_layout.addWidget(self.cycles_label)
        cycles_layout.addStretch()
        self.show_cycles_button = QPushButton("詳細を表示")
        self.show_cycles_button.setEnabled(False)
        self.show_cycles_button.clicked.connect(self.show_cycles_details)
        cycles_layout.addWidget(self.show_cycles_button)

        # 更新タブ
        update_tab = QWidget()
        update_layout = QVBoxLayout(update_tab)
        main_layout.addWidget(update_tab)

        # 更新オプション
        update_options_group = QGroupBox("更新オプション")
        update_options_layout = QVBoxLayout(update_options_group)
        update_layout.addWidget(update_options_group)

        # 更新対象選択
        self.update_all_radio = QRadioButton("すべてのモジュールを更新")
        self.update_all_radio.setChecked(True)
        update_options_layout.addWidget(self.update_all_radio)

        self.update_selected_radio = QRadioButton("選択したモジュールのみ更新")
        update_options_layout.addWidget(self.update_selected_radio)

        # モジュール選択リスト
        self.module_list = QListWidget()
        self.module_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self.module_list.setEnabled(False)
        update_options_layout.addWidget(self.module_list)

        # ラジオボタンの状態変更時の処理
        self.update_all_radio.toggled.connect(
            lambda checked: self.module_list.setEnabled(not checked)
        )

        # 更新ボタン
        update_button = QPushButton("__init__.pyファイルを更新")
        update_button.clicked.connect(self.update_init_files)
        update_options_layout.addWidget(update_button)

        # 更新結果表示
        self.update_result = QTextEdit()
        self.update_result.setReadOnly(True)
        update_layout.addWidget(self.update_result)

        # ボタンエリア
        button_layout = QHBoxLayout()
        main_layout.addLayout(button_layout)

        # ヘルプボタン
        help_button = QPushButton("ヘルプ")
        help_button.clicked.connect(self.show_help)
        button_layout.addWidget(help_button)

        button_layout.addStretch()

        # 閉じるボタン
        close_button = QPushButton("閉じる")
        close_button.clicked.connect(self.close)
        button_layout.addWidget(close_button)

    def analyze_dependencies(self):
        """依存関係の分析を実行"""
        # 進捗ダイアログの表示
        progress_dialog = QProgressDialog(
            "依存関係を分析中...", "キャンセル", 0, 100, self
        )
        progress_dialog.setWindowTitle("分析中")
        progress_dialog.setWindowModality(Qt.WindowModal)
        progress_dialog.setValue(10)
        QApplication.processEvents()

        try:
            # 依存関係の分析
            self.dependencies = analyzer.analyze_dependencies()
            progress_dialog.setValue(50)

            # フィルタリング
            filter_text = self.module_filter.text().strip()
            if filter_text:
                filtered_deps = {}
                for module, deps in self.dependencies.items():
                    if filter_text in module:
                        filtered_deps[module] = deps
                self.dependencies = filtered_deps

            # 循環依存の検出
            self.cycles = analyzer.detect_cycles(self.dependencies)
            progress_dialog.setValue(80)

            # 結果の表示
            self.update_dependency_tree()
            self.update_cycles_display()
            self.update_module_list()

            progress_dialog.setValue(100)

        except Exception as e:
            cmds.warning(f"依存関係の分析中にエラーが発生しました: {str(e)}")
            logger.error(f"依存関係の分析中にエラーが発生しました: {str(e)}")
        finally:
            progress_dialog.close()

    def update_dependency_tree(self):
        """依存関係ツリーの更新"""
        self.dependency_tree.clear()

        if not self.dependencies:
            return

        # モジュールをカテゴリごとにグループ化
        categories = {}
        for module in sorted(self.dependencies.keys()):
            parts = module.split(".")
            if len(parts) > 1:
                category = parts[1]  # ywta.category.module
                if category not in categories:
                    categories[category] = []
                categories[category].append(module)

        # カテゴリごとにツリーアイテムを作成
        for category in sorted(categories.keys()):
            category_item = QTreeWidgetItem(self.dependency_tree)
            category_item.setText(0, category)
            category_item.setExpanded(True)

            # モジュールごとのアイテムを作成
            for module in sorted(categories[category]):
                deps = self.dependencies[module]
                module_item = QTreeWidgetItem(category_item)
                module_item.setText(0, module)
                module_item.setText(1, str(len(deps)))

                # 依存モジュールを子アイテムとして追加
                for dep in sorted(deps):
                    dep_item = QTreeWidgetItem(module_item)
                    dep_item.setText(0, dep)

    def update_cycles_display(self):
        """循環依存の表示を更新"""
        if self.cycles:
            self.cycles_label.setText(f"{len(self.cycles)}個の循環依存が検出されました")
            self.show_cycles_button.setEnabled(True)
        else:
            self.cycles_label.setText("循環依存は検出されませんでした")
            self.show_cycles_button.setEnabled(False)

    def show_cycles_details(self):
        """循環依存の詳細を表示"""
        if not self.cycles:
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("循環依存の詳細")
        dialog.setMinimumWidth(500)

        layout = QVBoxLayout(dialog)

        # 循環依存リスト
        cycles_list = QListWidget()
        layout.addWidget(cycles_list)

        for i, cycle in enumerate(self.cycles, 1):
            cycles_list.addItem(f"循環{i}: {' -> '.join(cycle)}")

        # 閉じるボタン
        button_layout = QHBoxLayout()
        layout.addLayout(button_layout)

        button_layout.addStretch()
        close_button = QPushButton("閉じる")
        close_button.clicked.connect(dialog.close)
        button_layout.addWidget(close_button)

        dialog.exec_()

    def update_module_list(self):
        """モジュールリストの更新"""
        self.module_list.clear()

        if not self.dependencies:
            return

        # モジュールをリストに追加
        for module in sorted(self.dependencies.keys()):
            self.module_list.addItem(module)

    def update_init_files(self):
        """__init__.pyファイルの更新"""
        if not self.dependencies:
            cmds.warning("依存関係を先に分析してください")
            return

        # 進捗ダイアログの表示
        progress_dialog = QProgressDialog(
            "__init__.pyファイルを更新中...", "キャンセル", 0, 100, self
        )
        progress_dialog.setWindowTitle("更新中")
        progress_dialog.setWindowModality(Qt.WindowModal)
        progress_dialog.setValue(10)
        QApplication.processEvents()

        try:
            # 更新対象の選択
            if self.update_all_radio.isChecked():
                # すべてのモジュールを更新
                target_dependencies = self.dependencies
            else:
                # 選択されたモジュールのみ更新
                selected_modules = [
                    item.text() for item in self.module_list.selectedItems()
                ]
                if not selected_modules:
                    cmds.warning("更新するモジュールが選択されていません")
                    return

                target_dependencies = {
                    module: deps
                    for module, deps in self.dependencies.items()
                    if module in selected_modules
                }

            progress_dialog.setValue(30)

            # 更新前の状態を保存
            self.update_result.clear()
            self.update_result.append("__init__.pyファイルの更新を開始します...\n")

            # 更新の実行
            # 実際の更新処理をキャプチャするためにログハンドラを追加
            log_capture = []

            class LogHandler(logging.Handler):
                def emit(self, record):
                    log_capture.append(self.format(record))

            handler = LogHandler()
            handler.setFormatter(logging.Formatter("%(message)s"))
            logger.addHandler(handler)

            # 更新の実行
            analyzer.update_init_files(target_dependencies)
            progress_dialog.setValue(80)

            # ログの表示
            for log in log_capture:
                self.update_result.append(log)

            # ログハンドラの削除
            logger.removeHandler(handler)

            self.update_result.append("\n更新が完了しました")
            progress_dialog.setValue(100)

        except Exception as e:
            cmds.warning(f"__init__.pyファイルの更新中にエラーが発生しました: {str(e)}")
            logger.error(f"__init__.pyファイルの更新中にエラーが発生しました: {str(e)}")
        finally:
            progress_dialog.close()

    def show_help(self):
        """ヘルプの表示"""
        help_text = """
<h2>YWTA 依存関係分析ツール</h2>

<h3>概要</h3>
<p>このツールは、YWTAプロジェクト内のPythonモジュール間の依存関係を分析するためのものです。</p>

<h3>使用方法</h3>
<ol>
  <li><b>依存関係分析</b>: モジュールの依存関係を分析します。フィルタを使用して特定のモジュールに絞り込むことができます。</li>
  <li><b>__init__.py更新</b>: 分析結果に基づいて、各モジュールの__init__.pyファイルに依存関係情報を追加します。</li>
</ol>

<h3>注意事項</h3>
<ul>
  <li>__init__.pyファイルの更新は、既存のファイルを変更します。重要なファイルは事前にバックアップしてください。</li>
</ul>
"""

        dialog = QDialog(self)
        dialog.setWindowTitle("ヘルプ")
        dialog.setMinimumSize(600, 400)

        layout = QVBoxLayout(dialog)

        help_browser = QTextEdit()
        help_browser.setReadOnly(True)
        help_browser.setHtml(help_text)
        layout.addWidget(help_browser)

        button_layout = QHBoxLayout()
        layout.addLayout(button_layout)

        button_layout.addStretch()
        close_button = QPushButton("閉じる")
        close_button.clicked.connect(dialog.close)
        button_layout.addWidget(close_button)

        dialog.exec_()

    def closeEvent(self, event):
        """ウィンドウが閉じられるときの処理"""
        # シングルトンインスタンスのクリア
        self.__class__._window_instance = None
        event.accept()


def show():
    """依存関係分析ツールを表示"""
    DependencyVisualizerWindow.show_window()


if __name__ == "__main__":
    show()
