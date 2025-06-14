#!/usr/bin/env python
"""
YWTA Tools Blender テスト実行スクリプト

このスクリプトは、Blender環境でテストを実行するためのエントリーポイントを提供します。
Blender内から実行するか、blenderコマンドラインから実行します。
"""

import os
import sys
import argparse
from pathlib import Path

# プロジェクトルートをPythonパスに追加
project_root = str(Path(__file__).parent.parent.absolute())
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from tests.common.test_settings import TestSettings
from tests.utils.test_runner import run_blender_tests


def main():
    """Blender用テスト実行のメイン関数"""
    parser = argparse.ArgumentParser(description="YWTA Tools Blender テスト実行ツール")

    # テストタイプの選択
    parser.add_argument(
        "--type",
        choices=["unit", "integration", "performance"],
        default="unit",
        help="テストタイプ (デフォルト: unit)",
    )

    # テストディレクトリの指定
    parser.add_argument("--dir", help="テストを検索するディレクトリ")

    # テストファイルパターンの指定
    parser.add_argument(
        "--pattern",
        default="test_*.py",
        help="テストファイルのパターン (デフォルト: test_*.py)",
    )

    # 出力バッファリングの指定
    parser.add_argument(
        "--no-buffer", action="store_true", help="出力バッファリングを無効にする"
    )

    args = parser.parse_args()

    # 環境設定
    TestSettings.environment = "blender"
    TestSettings.test_mode = args.type
    TestSettings.buffer_output = not args.no_buffer

    # テストディレクトリが指定された場合
    if args.dir:
        test_dir = args.dir
    else:
        # デフォルトのテストディレクトリをタイプに基づいて決定
        test_dir = os.path.join(
            TestSettings.get_project_root(), "tests", "blender", args.type
        )

    # Blender用のテスト実行
    result = run_blender_tests(test_dir, args.pattern)

    # 終了コードの設定
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    # Blender環境内で実行されているかチェック
    try:
        import bpy

        main()
    except ImportError:
        # Blender環境外で実行された場合は警告を表示
        print("警告: このスクリプトはBlender環境内で実行する必要があります。")
        print("例: blender -b -P tests/run_blender_tests.py")
        sys.exit(1)
