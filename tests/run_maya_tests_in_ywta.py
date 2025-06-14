#!/usr/bin/env python3
"""
Command-line unit test runner for mayapy.

This can be used to run tests from a commandline environment like on a build server.

Usage:
    python run_maya_tests2.py -m 2024
"""

import argparse
import errno
import os
import platform
import shutil
import stat
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Optional, Union, List, Tuple, Any, Callable


# ルートディレクトリのパスを取得
YWTA_ROOT_DIR = Path(__file__).parent.parent.resolve()

print(f"YWTA_ROOT_DIR: {YWTA_ROOT_DIR}")


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


def remove_read_only(func: Callable, path: str, exc: Tuple[Any, Any, Any]) -> None:
    """読み取り専用ファイルに遭遇したときにshutil.rmtreeから呼び出されます。

    Args:
        func: 実行しようとした関数
        path: 操作対象のパス
        exc: 発生した例外情報

    Raises:
        RuntimeError: ファイルを削除できない場合
    """
    excvalue = exc[1]
    if func in (os.rmdir, os.remove) and excvalue.errno == errno.EACCES:
        os.chmod(path, stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)  # 0777
        func(path)
    else:
        raise RuntimeError(f"Could not remove {path}")


def main() -> None:
    """メイン実行関数。コマンドライン引数を解析し、Mayaテストを実行します。"""
    parser = argparse.ArgumentParser(
        description="Mayaモジュールのユニットテストを実行します",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("-m", "--maya", help="Mayaバージョン", type=int, default=2024)
    parser.add_argument(
        "-mad",
        "--maya-app-dir",
        help="クリーンなMAYA_APP_DIRを作成して終了",
        metavar="DIR",
    )

    args = parser.parse_args()
    mayaunittest = YWTA_ROOT_DIR / "maya" / "ywta" / "test" / "mayaunittest.py"
    mayapy_path = mayapy(args.maya)

    if not mayapy_path.exists():
        raise RuntimeError(
            f"Maya {args.maya} はこのシステムにインストールされていません。"
        )

    try:
        # 環境変数を設定

        os.environ["MAYA_MODULE_PATH"] = str(YWTA_ROOT_DIR)

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
