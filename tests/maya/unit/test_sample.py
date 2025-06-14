"""
Maya用サンプルテスト

このファイルは、Maya環境でのテスト作成方法を示すサンプルです。
"""

import os
import unittest
from tests.maya.maya_test_case import MayaTestCase


class SampleMayaTests(MayaTestCase):
    """Maya環境でのサンプルテストケース"""

    @classmethod
    def setUpClass(cls):
        """テストケースクラスの初期化"""
        super().setUpClass()
        # 必要に応じてプラグインをロード
        # cls.load_plugin('plugin_name.mll')

    def setUp(self):
        """各テスト前の準備"""
        super().setUp()
        # テスト固有のセットアップ

    def tearDown(self):
        """各テスト後のクリーンアップ"""
        # テスト固有のクリーンアップ
        super().tearDown()

    def test_basic_functionality(self):
        """基本機能のテスト"""
        # 基本的なアサーション
        self.assertEqual(1 + 1, 2)
        self.assertTrue(True)
        self.assertFalse(False)

    def test_maya_scene_creation(self):
        """Mayaシーン作成のテスト"""
        if not self.MAYA_AVAILABLE:
            self.skipTest("Maya環境が利用できません")

        # テスト用のノードを作成
        sphere = self.create_test_node("polySphere", "testSphere")
        self.assertIsNotNone(sphere)

        # 一時シーンファイルに保存
        temp_scene = self.get_temp_scene("test_sphere.ma")
        self.save_scene(temp_scene)

        # 新しいシーンを作成して、保存したシーンをロード
        self.new_scene()
        self.load_scene(temp_scene)

        # ロードされたシーンを検証
        import maya.cmds as cmds

        self.assertTrue(cmds.objExists("testSphere"))

    def test_with_temp_files(self):
        """一時ファイルを使用したテスト"""
        # 一時ファイルパスを取得
        temp_file = self.get_temp_filename("test_data.txt")

        # ファイルに書き込み
        with open(temp_file, "w") as f:
            f.write("Test data")

        # ファイルが存在することを確認
        self.assertTrue(os.path.exists(temp_file))

        # ファイルから読み込み
        with open(temp_file, "r") as f:
            content = f.read()

        # 内容を検証
        self.assertEqual(content, "Test data")

    def test_list_almost_equal(self):
        """浮動小数点リスト比較のテスト"""
        list1 = [1.0001, 2.0002, 3.0003]
        list2 = [1.0002, 2.0003, 3.0004]

        # 小数点以下3桁まで一致していればOK
        self.assertListAlmostEqual(list1, list2, places=3)

        # 小数点以下4桁では一致しない
        with self.assertRaises(AssertionError):
            self.assertListAlmostEqual(list1, list2, places=4)

    @unittest.skip("このテストはスキップされます")
    def test_skipped(self):
        """スキップされるテスト"""
        self.fail("このテストは実行されません")
