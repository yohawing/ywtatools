"""
基本テストケースモジュール

このモジュールは、Maya、Blenderなど異なるプラットフォーム間で共有される
テストケースの基底クラスを提供します。
"""

import os
import sys
import unittest
import shutil
import tempfile
import uuid
import logging
from pathlib import Path

from tests.common.test_settings import TestSettings


class BaseTestCase(unittest.TestCase):
    """すべてのテストケースの基底クラス

    このクラスは、プラットフォームに依存しない共通のテスト機能を提供します。
    Maya、Blenderなどの特定のプラットフォーム用のテストケースは、
    このクラスを継承して実装されます。
    """

    # テスト中に作成された一時ファイルのリスト
    files_created = []

    @classmethod
    def setUpClass(cls):
        """テストケースクラスの初期化"""
        super().setUpClass()

        # 一時ディレクトリが存在することを確認
        if not os.path.exists(TestSettings.temp_dir):
            os.makedirs(TestSettings.temp_dir)

    @classmethod
    def tearDownClass(cls):
        """テストケースクラスの終了処理"""
        super().tearDownClass()

        # 一時ファイルの削除
        cls.delete_temp_files()

    def setUp(self):
        """各テスト前の準備"""
        super().setUp()

        # テスト固有の設定があれば実装
        pass

    def tearDown(self):
        """各テスト後のクリーンアップ"""
        super().tearDown()

        # テスト固有のクリーンアップがあれば実装
        pass

    @classmethod
    def delete_temp_files(cls):
        """テスト中に作成された一時ファイルを削除"""
        if TestSettings.delete_files:
            for file_path in cls.files_created:
                if os.path.exists(file_path):
                    if os.path.isdir(file_path):
                        shutil.rmtree(file_path)
                    else:
                        os.remove(file_path)

            cls.files_created = []

            # 一時ディレクトリの削除
            if os.path.exists(TestSettings.temp_dir):
                shutil.rmtree(TestSettings.temp_dir)

    @classmethod
    def get_temp_filename(cls, file_name):
        """テストディレクトリ内の一意のファイルパス名を取得

        Args:
            file_name (str): ファイル名または相対パス (例: 'test.txt' または 'subdir/test.txt')

        Returns:
            str: 一時ファイルへのフルパス

        Note:
            ファイルは作成されません。作成は呼び出し元の責任です。
            このファイルはテスト終了時に削除されます。
        """
        temp_dir = TestSettings.temp_dir
        if not os.path.exists(temp_dir):
            os.makedirs(temp_dir)

        # サブディレクトリがある場合は作成
        subdir = os.path.dirname(file_name)
        if subdir:
            full_subdir = os.path.join(temp_dir, subdir)
            if not os.path.exists(full_subdir):
                os.makedirs(full_subdir)

        base_name, ext = os.path.splitext(os.path.basename(file_name))
        path = os.path.join(temp_dir, subdir, f"{base_name}{ext}")

        # 同名ファイルが存在する場合は連番を付与
        count = 0
        while os.path.exists(path):
            count += 1
            path = os.path.join(temp_dir, subdir, f"{base_name}{count}{ext}")

        cls.files_created.append(path)
        return path

    @classmethod
    def get_temp_dir(cls, dir_name):
        """テストディレクトリ内の一意のディレクトリパスを取得して作成

        Args:
            dir_name (str): ディレクトリ名または相対パス

        Returns:
            str: 作成された一時ディレクトリへのフルパス
        """
        temp_dir = TestSettings.temp_dir
        if not os.path.exists(temp_dir):
            os.makedirs(temp_dir)

        path = os.path.join(temp_dir, dir_name)

        # 同名ディレクトリが存在する場合は連番を付与
        count = 0
        while os.path.exists(path):
            count += 1
            path = os.path.join(temp_dir, f"{dir_name}{count}")

        os.makedirs(path)
        cls.files_created.append(path)
        return path

    def assertListAlmostEqual(self, first, second, places=7, msg=None, delta=None):
        """浮動小数点値のリストがほぼ等しいことをアサート

        Args:
            first (list): 最初のリスト
            second (list): 2番目のリスト
            places (int, optional): 小数点以下の桁数。デフォルトは7。
            msg (str, optional): カスタムエラーメッセージ
            delta (float, optional): 許容される最大差
        """
        self.assertEqual(len(first), len(second), msg)
        for a, b in zip(first, second):
            self.assertAlmostEqual(a, b, places, msg, delta)

    def assertDictAlmostEqual(self, first, second, places=7, msg=None, delta=None):
        """浮動小数点値を含む辞書がほぼ等しいことをアサート

        Args:
            first (dict): 最初の辞書
            second (dict): 2番目の辞書
            places (int, optional): 小数点以下の桁数。デフォルトは7。
            msg (str, optional): カスタムエラーメッセージ
            delta (float, optional): 許容される最大差
        """
        self.assertEqual(set(first.keys()), set(second.keys()), msg)
        for key in first:
            if isinstance(first[key], (float, int)) and isinstance(
                second[key], (float, int)
            ):
                self.assertAlmostEqual(first[key], second[key], places, msg, delta)
            elif isinstance(first[key], list) and isinstance(second[key], list):
                self.assertListAlmostEqual(first[key], second[key], places, msg, delta)
            elif isinstance(first[key], dict) and isinstance(second[key], dict):
                self.assertDictAlmostEqual(first[key], second[key], places, msg, delta)
            else:
                self.assertEqual(first[key], second[key], msg)
