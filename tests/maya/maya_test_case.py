"""
Maya テストケースモジュール

このモジュールは、Maya環境でのテスト実行のための基底クラスを提供します。
"""

import os
import sys
import unittest
import tempfile
import uuid
import logging

try:
    import maya.standalone

    # Mayaのスタンドアロンモードを初期化
    maya.standalone.initialize(name="python")
    # MayaのコマンドとMELをインポート
    import maya.cmds as cmds
    import maya.mel as mel

    MAYA_AVAILABLE = True
except ImportError:
    MAYA_AVAILABLE = False

from tests.common.base_test_case import BaseTestCase
from tests.common.test_settings import TestSettings


class MayaTestCase(BaseTestCase):
    """Maya環境でのテスト実行のための基底クラス

    このクラスは、Maya固有のテスト機能を提供します。
    Maya APIやコマンドを使用するテストは、このクラスを継承して実装します。
    """

    # ロードされたプラグインのリスト
    plugins_loaded = set()

    @classmethod
    def setUpClass(cls):
        """テストケースクラスの初期化"""
        super().setUpClass()

        # Maya環境のセットアップ
        TestSettings.setup_environment("maya")

        # Mayaが利用可能かチェック
        if not MAYA_AVAILABLE:
            raise unittest.SkipTest("Maya環境が利用できません。")

    @classmethod
    def tearDownClass(cls):
        """テストケースクラスの終了処理"""
        # プラグインのアンロード
        cls.unload_plugins()

        if float(cmds.about(v=True)) >= 2016.0:
            maya.standalone.uninitialize()

        super().tearDownClass()

    def setUp(self):
        """各テスト前の準備"""
        super().setUp()

        # 新しいシーンを作成
        if TestSettings.new_scene_between_tests:
            self.new_scene()

    def tearDown(self):
        """各テスト後のクリーンアップ"""
        super().tearDown()

    @classmethod
    def load_plugin(cls, plugin_name):
        """プラグインをロードし、テスト終了時にアンロードするために記録

        Args:
            plugin_name (str): プラグイン名

        Returns:
            bool: ロードに成功した場合はTrue
        """
        if not MAYA_AVAILABLE:
            return False

        try:
            if not cmds.pluginInfo(plugin_name, q=True, loaded=True):
                cmds.loadPlugin(plugin_name, quiet=True)
                cls.plugins_loaded.add(plugin_name)
            return True
        except:
            logging.warning(f"プラグイン '{plugin_name}' のロードに失敗しました。")
            return False

    @classmethod
    def unload_plugins(cls):
        """このテストケースでロードされたすべてのプラグインをアンロード"""
        if not MAYA_AVAILABLE:
            return

        for plugin in cls.plugins_loaded:
            try:
                if cmds.pluginInfo(plugin, q=True, loaded=True):
                    cmds.unloadPlugin(plugin, force=True)
            except:
                logging.warning(f"プラグイン '{plugin}' のアンロードに失敗しました。")

        cls.plugins_loaded.clear()

    def new_scene(self):
        """新しいMayaシーンを作成"""
        if MAYA_AVAILABLE:
            cmds.file(new=True, force=True)

    def load_scene(self, file_path):
        """Mayaシーンをロード

        Args:
            file_path (str): シーンファイルのパス

        Returns:
            bool: ロードに成功した場合はTrue
        """
        if not MAYA_AVAILABLE:
            return False

        try:
            cmds.file(file_path, open=True, force=True)
            return True
        except:
            logging.warning(f"シーンファイル '{file_path}' のロードに失敗しました。")
            return False

    def save_scene(self, file_path):
        """現在のMayaシーンを保存

        Args:
            file_path (str): 保存先のパス

        Returns:
            bool: 保存に成功した場合はTrue
        """
        if not MAYA_AVAILABLE:
            return False

        try:
            # ファイル拡張子に基づいてファイル形式を決定
            ext = os.path.splitext(file_path)[1].lower()
            if ext == ".mb":
                file_type = "mayaBinary"
            else:
                file_type = "mayaAscii"

            cmds.file(rename=file_path)
            cmds.file(save=True, type=file_type)
            return True
        except:
            logging.warning(f"シーンの保存に失敗しました: '{file_path}'")
            return False

    def get_temp_scene(self, scene_name="test_scene.ma"):
        """テスト用の一時シーンファイルパスを取得

        Args:
            scene_name (str, optional): シーンファイル名。デフォルトは "test_scene.ma"

        Returns:
            str: 一時シーンファイルへのフルパス
        """
        return self.get_temp_filename(scene_name)

    def create_test_node(self, node_type, name=None):
        """テスト用のノードを作成

        Args:
            node_type (str): ノードタイプ
            name (str, optional): ノード名

        Returns:
            str: 作成されたノードの名前
        """
        if not MAYA_AVAILABLE:
            return None

        kwargs = {}
        if name:
            kwargs["name"] = name

        try:
            return cmds.createNode(node_type, **kwargs)
        except:
            logging.warning(f"ノード '{node_type}' の作成に失敗しました。")
            return None

    def eval_mel(self, mel_script):
        """MELスクリプトを評価

        Args:
            mel_script (str): 実行するMELスクリプト

        Returns:
            object: MEL評価の結果
        """
        if not MAYA_AVAILABLE:
            return None

        try:
            return mel.eval(mel_script)
        except:
            logging.warning(f"MELスクリプトの実行に失敗しました: '{mel_script}'")
            return None
