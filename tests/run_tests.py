#!/usr/bin/env python
"""
YWTA Tools テスト実行スクリプト

このスクリプトは、コマンドラインからテストを実行するためのエントリーポイントを提供します。
"""

import os
import sys
import argparse
from pathlib import Path

# プロジェクトルートをPythonパスに追加
project_root = str(Path(__file__).parent.parent.absolute())
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from tests.run_maya_tests import run_maya_tests
from tests.run_blender_tests import run_blender_tests


def main():
    parser = argparse.ArgumentParser(description="YWTA Tools テスト実行スクリプト")

    args = parser.parse_args()

    run_maya_tests(
        maya_version=2024,  # Mayaのバージョンを指定
        test_dir=os.path.join(project_root, "tests", "maya", "unit"),
        pattern="test_*.py",  # テストファイルのパターン
    )
    # blender_testsはまだ実装されていないため、コメントアウトしています
    # run_blender_tests(verbosity=args.verbosity)


if __name__ == "__main__":
    main()
