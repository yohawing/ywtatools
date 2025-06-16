"""
Blender テストケースモジュール

このモジュールは、Blender環境でのテスト実行のための基底クラスを提供します。
"""

import os
import sys
import unittest
import tempfile
import uuid
import logging
from pathlib import Path

try:
    import bpy

    BLENDER_AVAILABLE = True
except ImportError:
    BLENDER_AVAILABLE = False

from tests.common.base_test_case import BaseTestCase
from tests.common.test_settings import TestSettings


class BlenderTestCase(BaseTestCase):
    """Blender環境でのテスト実行のための基底クラス

    このクラスは、Blender固有のテスト機能を提供します。
    Blender APIやアドオン機能を使用するテストは、このクラスを継承して実装します。
    """

    # 有効化されたアドオンのリスト
    addons_enabled = set()

    @classmethod
    def setUpClass(cls):
        """テストケースクラスの初期化"""
        super().setUpClass()

        # Blender環境のセットアップ
        TestSettings.setup_environment("blender")

        # Blenderが利用可能かチェック
        if not BLENDER_AVAILABLE:
            raise unittest.SkipTest("Blender環境が利用できません。")

    @classmethod
    def tearDownClass(cls):
        """テストケースクラスの終了処理"""
        # アドオンの無効化
        cls.disable_addons()

        super().tearDownClass()

    def setUp(self):
        """各テスト前の準備"""
        super().setUp()

        # 新しいシーンを作成
        if TestSettings.new_scene_between_tests and BLENDER_AVAILABLE:
            self.new_scene()

    def tearDown(self):
        """各テスト後のクリーンアップ"""
        super().tearDown()

    @classmethod
    def enable_addon(cls, addon_name):
        """アドオンを有効化し、テスト終了時に無効化するために記録

        Args:
            addon_name (str): アドオン名

        Returns:
            bool: 有効化に成功した場合はTrue
        """
        if not BLENDER_AVAILABLE:
            return False

        try:
            # アドオンが既に有効かチェック
            if not addon_name in bpy.context.preferences.addons:
                bpy.ops.preferences.addon_enable(module=addon_name)
                cls.addons_enabled.add(addon_name)
            return True
        except:
            logging.warning(f"アドオン '{addon_name}' の有効化に失敗しました。")
            return False

    @classmethod
    def disable_addons(cls):
        """このテストケースで有効化されたすべてのアドオンを無効化"""
        if not BLENDER_AVAILABLE:
            return

        for addon in cls.addons_enabled:
            try:
                if addon in bpy.context.preferences.addons:
                    bpy.ops.preferences.addon_disable(module=addon)
            except:
                logging.warning(f"アドオン '{addon}' の無効化に失敗しました。")

        cls.addons_enabled.clear()

    def new_scene(self):
        """新しいBlenderシーンを作成"""
        if BLENDER_AVAILABLE:
            # 既存のオブジェクトをすべて削除
            bpy.ops.object.select_all(action="SELECT")
            bpy.ops.object.delete()

            # 新しいシーンを作成
            bpy.ops.scene.new(type="EMPTY")

    def load_scene(self, file_path):
        """Blenderシーンをロード

        Args:
            file_path (str): シーンファイルのパス

        Returns:
            bool: ロードに成功した場合はTrue
        """
        if not BLENDER_AVAILABLE:
            return False

        try:
            bpy.ops.wm.open_mainfile(filepath=file_path)
            return True
        except:
            logging.warning(f"シーンファイル '{file_path}' のロードに失敗しました。")
            return False

    def save_scene(self, file_path):
        """現在のBlenderシーンを保存

        Args:
            file_path (str): 保存先のパス

        Returns:
            bool: 保存に成功した場合はTrue
        """
        if not BLENDER_AVAILABLE:
            return False

        try:
            bpy.ops.wm.save_as_mainfile(filepath=file_path)
            return True
        except:
            logging.warning(f"シーンの保存に失敗しました: '{file_path}'")
            return False

    def get_temp_scene(self, scene_name="test_scene.blend"):
        """テスト用の一時シーンファイルパスを取得

        Args:
            scene_name (str, optional): シーンファイル名。デフォルトは "test_scene.blend"

        Returns:
            str: 一時シーンファイルへのフルパス
        """
        return self.get_temp_filename(scene_name)

    def create_test_object(self, obj_type="MESH", name=None):
        """テスト用のオブジェクトを作成

        Args:
            obj_type (str, optional): オブジェクトタイプ。デフォルトは 'MESH'
            name (str, optional): オブジェクト名

        Returns:
            bpy.types.Object: 作成されたオブジェクト
        """
        if not BLENDER_AVAILABLE:
            return None

        try:
            # オブジェクトタイプに基づいて適切な作成関数を呼び出す
            if obj_type == "MESH":
                bpy.ops.mesh.primitive_cube_add()
            elif obj_type == "CURVE":
                bpy.ops.curve.primitive_bezier_curve_add()
            elif obj_type == "ARMATURE":
                bpy.ops.object.armature_add()
            elif obj_type == "EMPTY":
                bpy.ops.object.empty_add()
            else:
                # デフォルトはメッシュ
                bpy.ops.mesh.primitive_cube_add()

            # 作成されたオブジェクトを取得
            obj = bpy.context.active_object

            # 名前を設定
            if name:
                obj.name = name

            return obj
        except:
            logging.warning(f"オブジェクト '{obj_type}' の作成に失敗しました。")
            return None

    def run_operator(self, operator_path, **kwargs):
        """Blenderオペレータを実行

        Args:
            operator_path (str): オペレータのパス (例: "object.select_all")
            **kwargs: オペレータに渡す引数

        Returns:
            set: オペレータの実行結果
        """
        if not BLENDER_AVAILABLE:
            return {"CANCELLED"}

        try:
            # オペレータパスを分解
            category, name = operator_path.split(".")
            operator = getattr(getattr(bpy.ops, category), name)

            # オペレータを実行
            return operator(**kwargs)
        except:
            logging.warning(f"オペレータ '{operator_path}' の実行に失敗しました。")
            return {"CANCELLED"}
