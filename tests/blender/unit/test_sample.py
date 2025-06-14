"""
Blender用サンプルテスト

このファイルは、Blender環境でのテスト作成方法を示すサンプルです。
"""

import os
import unittest
from tests.blender.blender_test_case import BlenderTestCase


class SampleBlenderTests(BlenderTestCase):
    """Blender環境でのサンプルテストケース"""

    @classmethod
    def setUpClass(cls):
        """テストケースクラスの初期化"""
        super().setUpClass()
        # 必要に応じてアドオンを有効化
        # cls.enable_addon('ywtatools_addon')

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

    def test_blender_object_creation(self):
        """Blenderオブジェクト作成のテスト"""
        if not self.BLENDER_AVAILABLE:
            self.skipTest("Blender環境が利用できません")

        # テスト用のオブジェクトを作成
        cube = self.create_test_object("MESH", "TestCube")
        self.assertIsNotNone(cube)

        # オブジェクトのプロパティを検証
        self.assertEqual(cube.name, "TestCube")
        self.assertEqual(cube.type, "MESH")

        # 一時シーンファイルに保存
        temp_scene = self.get_temp_scene("test_cube.blend")
        self.save_scene(temp_scene)

        # 新しいシーンを作成して、保存したシーンをロード
        self.new_scene()
        self.load_scene(temp_scene)

        # ロードされたシーンを検証
        import bpy

        self.assertIn("TestCube", bpy.data.objects)

    def test_blender_operator(self):
        """Blenderオペレータのテスト"""
        if not self.BLENDER_AVAILABLE:
            self.skipTest("Blender環境が利用できません")

        # オペレータを実行
        result = self.run_operator("mesh.primitive_cube_add")

        # 結果を検証
        self.assertEqual(result, {"FINISHED"})

        import bpy

        # 新しいキューブが作成されたことを確認
        self.assertEqual(len(bpy.context.selected_objects), 1)
        self.assertEqual(bpy.context.active_object.type, "MESH")

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

    def test_dict_almost_equal(self):
        """浮動小数点辞書比較のテスト"""
        dict1 = {"a": 1.0001, "b": 2.0002, "c": {"d": 3.0003}}
        dict2 = {"a": 1.0002, "b": 2.0003, "c": {"d": 3.0004}}

        # 小数点以下3桁まで一致していればOK
        self.assertDictAlmostEqual(dict1, dict2, places=3)

        # 小数点以下4桁では一致しない
        with self.assertRaises(AssertionError):
            self.assertDictAlmostEqual(dict1, dict2, places=4)

    @unittest.skip("このテストはスキップされます")
    def test_skipped(self):
        """スキップされるテスト"""
        self.fail("このテストは実行されません")
