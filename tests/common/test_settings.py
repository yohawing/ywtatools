"""
テスト設定モジュール

このモジュールは、テスト実行に関する設定と環境変数を管理します。
"""

import os
import sys
import tempfile
import uuid
import logging
from pathlib import Path


class TestSettings:
    """テスト実行のためのグローバル設定を管理するクラス"""

    # テスト中に生成される一時ファイルの保存場所
    # 並行実行時の競合を避けるためにUUIDサブディレクトリを使用
    temp_dir = os.path.join(tempfile.gettempdir(), "ywtatools_tests", str(uuid.uuid4()))

    # テスト終了後に一時ファイルを削除するかどうか
    delete_files = True

    # テスト実行中に標準出力と標準エラーをバッファリングするかどうか
    # 成功したテストの出力は破棄され、失敗したテストの出力のみが表示される
    buffer_output = True

    # テスト間で新しいシーンを作成するかどうか（Maya/Blender固有）
    new_scene_between_tests = True

    # テスト実行環境（'maya', 'blender', 'standalone'）
    environment = "standalone"

    # テスト実行モード（'unit', 'integration', 'performance'）
    test_mode = "unit"

    # プロジェクトのルートディレクトリ
    @classmethod
    def get_project_root(cls):
        """プロジェクトのルートディレクトリを取得"""
        # このファイルの場所から相対的にプロジェクトルートを特定
        return str(Path(__file__).parent.parent.parent.absolute())

    @classmethod
    def get_maya_scripts_dir(cls):
        """Mayaスクリプトディレクトリを取得"""
        return os.path.join(cls.get_project_root(), "maya")

    @classmethod
    def get_blender_addons_dir(cls):
        """Blenderアドオンディレクトリを取得"""
        return os.path.join(cls.get_project_root(), "blender", "addons")

    @classmethod
    def setup_environment(cls, env_type):
        """テスト環境をセットアップ

        Args:
            env_type (str): 環境タイプ ('maya', 'blender', 'standalone')
        """
        cls.environment = env_type

        # 環境に応じたパス設定
        if env_type == "maya":
            # Mayaモジュールパスを追加
            maya_path = cls.get_maya_scripts_dir()
            if maya_path not in sys.path:
                sys.path.insert(0, maya_path)

        elif env_type == "blender":
            # Blenderアドオンパスを追加
            blender_path = cls.get_blender_addons_dir()
            if blender_path not in sys.path:
                sys.path.insert(0, blender_path)

    @classmethod
    def set_temp_dir(cls, directory):
        """テストから生成されたファイルを保存する場所を設定

        Args:
            directory (str): ディレクトリパス
        """
        if os.path.exists(directory):
            cls.temp_dir = directory
        else:
            raise RuntimeError(f"{directory} が存在しません。")

    @classmethod
    def set_delete_files(cls, value):
        """テスト終了後に一時ファイルを削除するかどうかを設定

        Args:
            value (bool): 削除する場合はTrue
        """
        cls.delete_files = value

    @classmethod
    def set_buffer_output(cls, value):
        """テスト実行中に出力をバッファリングするかどうかを設定

        Args:
            value (bool): バッファリングする場合はTrue
        """
        cls.buffer_output = value

        if value:
            # テスト実行中のログを無効化
            logging.disable(logging.CRITICAL)
        else:
            # ログ状態を復元
            logging.disable(logging.NOTSET)

    @classmethod
    def set_new_scene_between_tests(cls, value):
        """テスト間で新しいシーンを作成するかどうかを設定

        Args:
            value (bool): 新しいシーンを作成する場合はTrue
        """
        cls.new_scene_between_tests = value
