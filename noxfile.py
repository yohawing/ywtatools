"""ywtatools の開発用タスクランナー。

新しいビルド・検証タスクは設定ファイルを増やさないため、原則としてここに
Nox セッションとして追加する。venv は作らず（venv_backend="none"）、既存の
Python環境 / mayapy / blender を薄くラップして呼び出すだけにする。

よく使うコマンド:
    uvx nox -s lint
    uvx nox -s maya_tests
    uvx nox -s maya_tests -- --type integration
    uvx nox -s blender_tests
    uvx nox -s blender_tests -- --type integration
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import nox

nox.options.sessions = ["lint"]


@nox.session(venv_backend="none")
def lint(session: nox.Session) -> None:
    """ruff check を実行する。

    Examples:
        uvx nox -s lint
    """
    session.run("ruff", "check", *(session.posargs or ["."]), external=True)


@nox.session(venv_backend="none")
def maya_tests(session: nox.Session) -> None:
    """tests/run_maya_tests.py をラップして実行する。

    引数は tests/run_maya_tests.py にそのまま渡す（--type, --pattern, --maya 等）。

    Examples:
        uvx nox -s maya_tests
        uvx nox -s maya_tests -- --type integration
        uvx nox -s maya_tests -- --type unit --maya 2024
    """
    session.run(
        sys.executable,
        "tests/run_maya_tests.py",
        *session.posargs,
        external=True,
    )


@nox.session(venv_backend="none")
def autoremesher_build(session: nox.Session) -> None:
    """AutoRemesher コア（cpp/autoremesher_core）を CMake でビルドし、
    生成した ywta_autoremesher.dll を bin/windows/ にコピーする。

    external/autoremesher submodule (タグ 1.0.0) を Qt 抜き・VS2022 + CMake の
    みでビルドする。要 VS2022 (Visual Studio Build Tools含む) + CMake。

    Examples:
        uvx nox -s autoremesher_build
    """
    repo_root = Path(__file__).parent
    src_dir = repo_root / "cpp" / "autoremesher_core"
    build_dir = src_dir / "build"

    submodule_marker = repo_root / "external" / "autoremesher" / "src" / "AutoRemesher" / "autoremesher.h"
    if not submodule_marker.exists():
        session.error(
            "external/autoremesher submodule が見つかりません。"
            "`git submodule update --init` を実行してください。"
        )

    # Ninja は cl.exe が PATH 上にある（Developer Command Prompt等でvcvarsが
    # 通っている）場合のみ使う。それ以外は VS2022 のジェネレータが
    # vcvars不要でMSVCを自動検出できるため既定とする。
    generator = "Visual Studio 17 2022"
    if shutil.which("ninja") and shutil.which("cl"):
        generator = "Ninja"

    configure_args = [
        "cmake",
        "-S",
        str(src_dir),
        "-B",
        str(build_dir),
        "-G",
        generator,
    ]
    if generator == "Visual Studio 17 2022":
        configure_args += ["-A", "x64"]
    else:
        configure_args += ["-DCMAKE_BUILD_TYPE=Release"]
    session.run(*configure_args, external=True)

    session.run(
        "cmake",
        "--build",
        str(build_dir),
        "--config",
        "Release",
        "--target",
        "ywta_autoremesher",
        "--parallel",
        external=True,
    )

    built_dll = build_dir / "output" / "Release" / "ywta_autoremesher.dll"
    if not built_dll.exists():
        # Ninja 等のシングルコンフィグジェネレータでは Release サブディレクトリを作らない
        built_dll = build_dir / "output" / "ywta_autoremesher.dll"
    if not built_dll.exists():
        session.error(f"ビルド後にDLLが見つかりません: {built_dll}")

    out_dir = repo_root / "bin" / "windows"
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / "ywta_autoremesher.dll"
    shutil.copy2(built_dll, dest)
    session.log(f"コピー完了: {built_dll} -> {dest}")


@nox.session(venv_backend="none")
def mesh_core_tests(session: nox.Session) -> None:
    """DCC 非依存メッシュコアをビルドして純 C++ テストを実行する。

    Examples:
        uvx nox -s mesh_core_tests
    """
    repo_root = Path(__file__).parent
    src_dir = repo_root / "cpp" / "mesh_core"
    build_dir = src_dir / "build"

    # 通常のPowerShellからでも、VS2022環境を有効化してNinjaを使えるようにする。
    # Visual Studio generatorのcompiler probeが他のMSBuildと競合して停止することを避ける。
    if shutil.which("ninja") and not shutil.which("cl"):
        build_dir = src_dir / "build-vs2022-ninja"
        vswhere = Path(
            r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe"
        )
        if not vswhere.exists():
            session.error("VS2022の検出に必要なvswhere.exeが見つかりません")
        installation = subprocess.run(
            [
                str(vswhere),
                "-latest",
                "-products",
                "*",
                "-version",
                "[17.0,18.0)",
                "-requires",
                "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                "-property",
                "installationPath",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if not installation:
            session.error("VS2022 C++ toolchainが見つかりません")
        vsdevcmd = Path(installation) / "Common7" / "Tools" / "VsDevCmd.bat"
        environment_result = subprocess.run(
            f'call "{vsdevcmd}" -arch=x64 >nul && set',
            check=True,
            capture_output=True,
            text=True,
            shell=True,
        )
        build_environment = dict(
            line.split("=", 1)
            for line in environment_result.stdout.splitlines()
            if "=" in line
        )
        session.run(
            "cmake",
            "-S",
            str(src_dir),
            "-B",
            str(build_dir),
            "-G",
            "Ninja",
            "-DCMAKE_BUILD_TYPE=Release",
            external=True,
            env=build_environment,
        )
        session.run(
            "cmake",
            "--build",
            str(build_dir),
            "--parallel",
            external=True,
            env=build_environment,
        )
        session.run(
            "ctest",
            "--test-dir",
            str(build_dir),
            "--output-on-failure",
            external=True,
            env=build_environment,
        )
        return

    generator = "Visual Studio 17 2022"
    if shutil.which("ninja") and shutil.which("cl"):
        generator = "Ninja"

    configure_args = [
        "cmake",
        "-S",
        str(src_dir),
        "-B",
        str(build_dir),
        "-G",
        generator,
    ]
    if generator == "Visual Studio 17 2022":
        configure_args += ["-A", "x64"]
    else:
        configure_args += ["-DCMAKE_BUILD_TYPE=Release"]
    session.run(*configure_args, external=True)
    session.run(
        "cmake",
        "--build",
        str(build_dir),
        "--config",
        "Release",
        "--parallel",
        external=True,
    )
    session.run(
        "ctest",
        "--test-dir",
        str(build_dir),
        "--build-config",
        "Release",
        "--output-on-failure",
        external=True,
    )


@nox.session(venv_backend="none")
def blender_tests(session: nox.Session) -> None:
    """tests/run_blender_tests.py をラップして実行する。

    引数は tests/run_blender_tests.py にそのまま渡す（--type 等）。

    Examples:
        uvx nox -s blender_tests
        uvx nox -s blender_tests -- --type integration
    """
    session.run(
        sys.executable,
        "tests/run_blender_tests.py",
        *session.posargs,
        external=True,
    )
