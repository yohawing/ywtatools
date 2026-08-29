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
import tempfile
from pathlib import Path

# プロジェクトルートをPythonパスに追加
YWTA_ROOT_DIR = str(Path(__file__).parent.parent.absolute())
if YWTA_ROOT_DIR not in sys.path:
    sys.path.insert(0, YWTA_ROOT_DIR)


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

    parser.add_argument(
        "--type",
        choices=["unit", "integration", "performance"],
        default="unit",
        help="テストタイプ (デフォルト: unit)",
    )

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

    args = parser.parse_args()

    # プロジェクトルートを取
    mayapy_path = mayapy(args.maya)

    maya_unit_test = os.path.join(YWTA_ROOT_DIR, "maya", "ywta", "test", "maya_unit_test.py")

    # mayapyを使用してテストを実行
    command = [
        str(mayapy_path),
        str(maya_unit_test),
        "--maya",
        str(args.maya),
        "--type",
        args.type,
        "--pattern",
        args.pattern,
    ]
    environment = os.environ.copy()
    environment["MAYA_SCRIPT_PATH"] = ""
    environment["MAYA_MODULE_PATH"] = YWTA_ROOT_DIR

    try:
        with tempfile.TemporaryDirectory(prefix="ywta_maya_tests_") as maya_app_dir:
            environment["MAYA_APP_DIR"] = maya_app_dir
            subprocess.check_call(command, env=environment, cwd=maya_app_dir)
    except subprocess.CalledProcessError as e:
        print(f"テストの実行に失敗しました: {e}")
        sys.exit(1)

    print("テストが正常に実行されました。")


if __name__ == "__main__":
    main()
