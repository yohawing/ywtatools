"""
テスト実行ユーティリティモジュール

このモジュールは、テストの検出と実行のためのユーティリティ関数を提供します。
"""

import os
import sys
import unittest
import argparse
import logging
import importlib
from pathlib import Path

from tests.common.test_settings import TestSettings


def discover_tests(test_dir, pattern="test_*.py"):
    """指定されたディレクトリからテストを検出

    Args:
        test_dir (str): テストを検索するディレクトリ
        pattern (str, optional): テストファイルのパターン。デフォルトは "test_*.py"

    Returns:
        unittest.TestSuite: 検出されたテストのTestSuite
    """
    loader = unittest.TestLoader()
    suite = loader.discover(test_dir, pattern=pattern)
    return suite


def run_tests(test_suite, verbosity=2, buffer=True):
    """テストスイートを実行

    Args:
        test_suite (unittest.TestSuite): 実行するテストスイート
        verbosity (int, optional): 詳細レベル。デフォルトは2
        buffer (bool, optional): 出力をバッファリングするかどうか。デフォルトはTrue

    Returns:
        unittest.TestResult: テスト実行結果
    """
    runner = unittest.TextTestRunner(verbosity=verbosity, buffer=buffer)
    return runner.run(test_suite)


def run_specific_test(test_path):
    """特定のテストを実行

    Args:
        test_path (str): テストパス (例: "tests.maya.unit.test_config.ConfigTests.test_basic")

    Returns:
        unittest.TestResult: テスト実行結果
    """
    loader = unittest.TestLoader()
    try:
        suite = loader.loadTestsFromName(test_path)
        return run_tests(suite)
    except (ImportError, AttributeError) as e:
        logging.error(f"テスト '{test_path}' のロードに失敗しました: {e}")
        return None


def run_maya_tests(test_dir=None, pattern="test_*.py"):
    """Maya用のテストを実行

    Args:
        test_dir (str, optional): テストディレクトリ。指定されない場合は tests/maya/unit
        pattern (str, optional): テストファイルのパターン。デフォルトは "test_*.py"

    Returns:
        unittest.TestResult: テスト実行結果
    """
    # Maya環境のセットアップ
    TestSettings.setup_environment("maya")

    # テストディレクトリが指定されていない場合はデフォルトを使用
    if test_dir is None:
        test_dir = os.path.join(
            TestSettings.get_project_root(), "tests", "maya", "unit"
        )

    # テストを検出して実行
    suite = discover_tests(test_dir, pattern)
    return run_tests(suite)


def run_blender_tests(test_dir=None, pattern="test_*.py"):
    """Blender用のテストを実行

    Args:
        test_dir (str, optional): テストディレクトリ。指定されない場合は tests/blender/unit
        pattern (str, optional): テストファイルのパターン。デフォルトは "test_*.py"

    Returns:
        unittest.TestResult: テスト実行結果
    """
    # Blender環境のセットアップ
    TestSettings.setup_environment("blender")

    # テストディレクトリが指定されていない場合はデフォルトを使用
    if test_dir is None:
        test_dir = os.path.join(
            TestSettings.get_project_root(), "tests", "blender", "unit"
        )

    # テストを検出して実行
    suite = discover_tests(test_dir, pattern)
    return run_tests(suite)


def main():
    """コマンドラインからのテスト実行のためのメイン関数"""
    parser = argparse.ArgumentParser(description="YWTA Tools テスト実行ツール")

    # 環境の選択
    parser.add_argument(
        "--env",
        choices=["maya", "blender", "standalone"],
        default="standalone",
        help="テスト実行環境 (デフォルト: standalone)",
    )

    # テストタイプの選択
    parser.add_argument(
        "--type",
        choices=["unit", "integration", "performance"],
        default="unit",
        help="テストタイプ (デフォルト: unit)",
    )

    # 特定のテストの実行
    parser.add_argument(
        "--test",
        help="実行する特定のテスト (例: tests.maya.unit.test_config.ConfigTests.test_basic)",
    )

    # テストディレクトリの指定
    parser.add_argument("--dir", help="テストを検索するディレクトリ")

    # テストファイルパターンの指定
    parser.add_argument(
        "--pattern",
        default="test_*.py",
        help="テストファイルのパターン (デフォルト: test_*.py)",
    )

    # 詳細レベルの指定
    parser.add_argument(
        "--verbose", "-v", action="count", default=1, help="詳細レベルを増やす"
    )

    # 出力バッファリングの指定
    parser.add_argument(
        "--no-buffer", action="store_true", help="出力バッファリングを無効にする"
    )

    args = parser.parse_args()

    # 環境設定
    TestSettings.environment = args.env
    TestSettings.test_mode = args.type
    TestSettings.buffer_output = not args.no_buffer

    # 特定のテストが指定された場合
    if args.test:
        result = run_specific_test(args.test)
        sys.exit(0 if result and result.wasSuccessful() else 1)

    # テストディレクトリが指定された場合
    if args.dir:
        test_dir = args.dir
    else:
        # デフォルトのテストディレクトリを環境とタイプに基づいて決定
        test_dir = os.path.join(
            TestSettings.get_project_root(), "tests", args.env, args.type
        )

    # 環境に応じたテスト実行
    if args.env == "maya":
        result = run_maya_tests(test_dir, args.pattern)
    elif args.env == "blender":
        result = run_blender_tests(test_dir, args.pattern)
    else:
        # スタンドアロンモードでのテスト実行
        suite = discover_tests(test_dir, args.pattern)
        result = run_tests(suite, verbosity=args.verbose, buffer=not args.no_buffer)

    # 終了コードの設定
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
