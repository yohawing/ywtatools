#!/usr/bin/env python
"""
YWTA Tools Maya テスト実行スクリプト

このスクリプトは、Maya環境でテストを実行するためのエントリーポイントを提供します。
Maya内から実行するか、mayapy.exeを使用して実行します。
"""

import os
import platform
import subprocess
import sys
import argparse
from pathlib import Path

# プロジェクトルートをPythonパスに追加
project_root = str(Path(__file__).parent.parent.absolute())
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from tests.common.test_settings import TestSettings
from tests.utils.test_runner import run_maya_tests


def get_maya_location(maya_version: int) -> Path:
    """Mayaがインストールされている場所を取得します。

    Args:
        maya_version: Mayaのバージョン番号

    Returns:
        Mayaがインストールされているパス

    Examples:
        >>> get_maya_location(2024)
        Path('C:/Program Files/Autodesk/Maya2024')
    """
    if "MAYA_LOCATION" in os.environ:
        return Path(os.environ["MAYA_LOCATION"])

    if platform.system() == "Windows":
        return Path(f"C:\\Program Files\\Autodesk\\Maya{maya_version}")
    elif platform.system() == "Darwin":
        return Path(f"/Applications/Autodesk/maya{maya_version}/Maya.app/Contents")
    else:
        location = f"/usr/autodesk/maya{maya_version}"
        if maya_version < 2016:
            # 2016以降、デフォルトのインストールディレクトリ名が変更されました
            location += "-x64"
        return Path(location)


def mayapy(maya_version: int) -> Path:
    """mayapy実行ファイルのパスを取得します。

    Args:
        maya_version: Mayaのバージョン番号

    Returns:
        mayapy実行ファイルのパス

    Examples:
        >>> mayapy(2024)
        Path('C:/Program Files/Autodesk/Maya2024/bin/mayapy.exe')
    """
    python_exe = get_maya_location(maya_version) / "bin" / "mayapy"
    if platform.system() == "Windows":
        python_exe = python_exe.with_suffix(".exe")
    return python_exe


def main():
    """Maya用テスト実行のメイン関数"""
    parser = argparse.ArgumentParser(description="YWTA Tools Maya テスト実行ツール")

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

    # Mayaバージョンの指定
    parser.add_argument(
        "-m",
        "--maya",
        type=int,
        default=2024,
        help="Mayaのバージョン (デフォルト: 2024)",
    )

    # 出力バッファリングの指定
    parser.add_argument(
        "--no-buffer", action="store_true", help="出力バッファリングを無効にする"
    )

    args = parser.parse_args()

    # 環境設定
    TestSettings.environment = "maya"
    TestSettings.test_mode = args.type
    TestSettings.buffer_output = not args.no_buffer

    # テストディレクトリが指定された場合
    if args.dir:
        test_dir = args.dir
    else:
        # デフォルトのテストディレクトリをタイプに基づいて決定
        test_dir = os.path.join(
            TestSettings.get_project_root(), "tests", "maya", args.type
        )

    # Maya用のテスト実行
    # result = run_maya_tests(test_dir, args.pattern)

    # 環境変数を設定

    try:
        mayaunittest = Path(project_root) / "maya" / "ywta" / "test" / "mayaunittest.py"
        mayapy_path = mayapy(args.maya)

        os.environ["MAYA_MODULE_PATH"] = str(project_root)

        # テストを実行
        cmd = [str(mayapy_path), str(mayaunittest)]
        print(f"テストを実行中: {' '.join(cmd)}")

        result = subprocess.run(
            cmd,
            check=False,  # エラーが発生しても例外をスローしない
            capture_output=True,
            text=True,
        )

        # 出力を表示
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(f"エラー出力:\n{result.stderr}")

        # 終了コードを返す
        if result.returncode != 0:
            print(f"テスト実行が失敗しました。終了コード: {result.returncode}")
        else:
            print("テスト実行が成功しました。")

    except Exception as e:
        print(f"テスト実行中にエラーが発生しました: {e}")
        raise


if __name__ == "__main__":
    main()
