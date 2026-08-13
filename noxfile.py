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
    uvx nox -s photoshop_validate
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import nox

nox.options.sessions = ["lint"]


MAYA_PLUGIN_VERSIONS = (2025, 2026, 2027)


def _resolve_maya_plugin_versions(posargs: Sequence[str]) -> tuple[int, ...]:
    """Mayaプラグインビルド対象を検証して整数のタプルへ変換する。"""
    requested = tuple(posargs) or tuple(str(version) for version in MAYA_PLUGIN_VERSIONS)
    versions: list[int] = []
    for raw_version in requested:
        if not raw_version.isdecimal():
            raise ValueError(f"Mayaバージョンは数字で指定してください: {raw_version}")
        version = int(raw_version)
        if version not in MAYA_PLUGIN_VERSIONS:
            supported = ", ".join(str(item) for item in MAYA_PLUGIN_VERSIONS)
            raise ValueError(f"未対応のMayaバージョンです: {version}（対応: {supported}）")
        versions.append(version)
    return tuple(versions)


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
def maya_plugin_build(session: nox.Session) -> None:
    """Maya 2025以降のC++プラグインをバージョンごとに順番にビルドする。

    引数を省略すると2025、2026、2027を順にビルドする。明示した場合は
    対応済みのバージョンだけを受け付ける。

    Examples:
        uvx nox -s maya_plugin_build
        uvx nox -s maya_plugin_build -- 2026
        uvx nox -s maya_plugin_build -- 2025 2027
    """
    try:
        versions = _resolve_maya_plugin_versions(session.posargs)
    except ValueError as error:
        session.error(str(error))

    build_script = Path(__file__).parent / "maya" / "cpp" / "build.bat"
    if not build_script.is_file():
        session.error(f"Mayaプラグインのビルドスクリプトが見つかりません: {build_script}")

    for version in versions:
        session.run(
            "cmd",
            "/c",
            str(build_script),
            str(version),
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
        session.error("external/autoremesher submodule が見つかりません。`git submodule update --init` を実行してください。")

    # 通常のPowerShellでもVS2022環境を注入し、停止しやすいMSBuild経路を避ける。
    build_environment = None
    generator = "Visual Studio 17 2022"
    if shutil.which("ninja") and not shutil.which("cl"):
        build_dir = src_dir / "build-vs2022-ninja"
        vswhere = Path(r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe")
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
        build_environment = dict(line.split("=", 1) for line in environment_result.stdout.splitlines() if "=" in line)
        generator = "Ninja"
    elif shutil.which("ninja") and shutil.which("cl"):
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
    session.run(*configure_args, external=True, env=build_environment)

    session.run(
        "cmake",
        "--build",
        str(build_dir),
        "--config",
        "Release",
        "--parallel",
        external=True,
        env=build_environment,
    )
    session.run(
        "ctest",
        "--test-dir",
        str(build_dir),
        "--build-config",
        "Release",
        "--output-on-failure",
        external=True,
        env=build_environment,
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


def _build_mesh_smoothing_dll(session: nox.Session) -> Path:
    """RustメッシュスムージングDLLをビルドしてbin/windowsへコピーする。"""
    repo_root = Path(__file__).parent
    session.run(
        "cargo",
        "build",
        "--release",
        "-p",
        "ywta-mesh-smoothing",
        external=True,
    )
    built_dll = repo_root / "target" / "release" / "ywta_mesh_smoothing.dll"
    if not built_dll.exists():
        session.error(f"ビルド後にDLLが見つかりません: {built_dll}")
    out_dir = repo_root / "bin" / "windows"
    out_dir.mkdir(parents=True, exist_ok=True)
    destination = out_dir / "ywta_mesh_smoothing.dll"
    shutil.copy2(built_dll, destination)
    session.log(f"コピー完了: {built_dll} -> {destination}")
    return destination


@nox.session(venv_backend="none")
def mesh_smoothing_build(session: nox.Session) -> None:
    """RustメッシュスムージングのリリースDLLをビルドする。"""
    _build_mesh_smoothing_dll(session)


@nox.session(venv_backend="none")
def mesh_smoothing_ffi_smoke(session: nox.Session) -> None:
    """DLLをビルドし、Python ctypesからC ABIの往復を検証する。"""
    dll_path = _build_mesh_smoothing_dll(session)
    environment = dict(os.environ)
    environment["YWTA_MESH_SMOOTHING_DLL"] = str(dll_path)
    session.run(
        sys.executable,
        "tests/native/test_ywta_mesh_smoothing_ffi.py",
        env=environment,
        external=True,
    )


def _resolve_blender_executable(session: nox.Session) -> Path:
    """環境変数、PATH、Windows標準配置の順でBlenderを解決する。"""
    configured = os.environ.get("BLENDER_EXECUTABLE")
    if configured:
        executable = Path(configured)
        if executable.is_file():
            return executable
        session.error(f"BLENDER_EXECUTABLEが指すファイルが見つかりません: {executable}")

    from_path = shutil.which("blender")
    if from_path:
        return Path(from_path)

    if os.name == "nt":
        program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        install_root = program_files / "Blender Foundation"
        candidates = list(install_root.glob("Blender */blender.exe"))
        if candidates:

            def version_key(executable: Path) -> tuple[int, ...]:
                """インストールフォルダ名から数値バージョンを返す。"""
                version = executable.parent.name.removeprefix("Blender ")
                try:
                    return tuple(int(part) for part in version.split("."))
                except ValueError:
                    return ()

            return max(candidates, key=version_key)

    session.error(
        "Blender実行ファイルが見つかりません。PATHへ追加するか、"
        "BLENDER_EXECUTABLEにblender実行ファイルの絶対パスを設定してください。"
    )


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
        vswhere = Path(r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe")
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
        build_environment = dict(line.split("=", 1) for line in environment_result.stdout.splitlines() if "=" in line)
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
        built_dll = build_dir / "ywta_mesh_core.dll"
        out_dir = repo_root / "bin" / "windows"
        out_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(built_dll, out_dir / built_dll.name)
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
    built_dll = build_dir / "Release" / "ywta_mesh_core.dll"
    if generator == "Ninja":
        built_dll = build_dir / "ywta_mesh_core.dll"
    out_dir = repo_root / "bin" / "windows"
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(built_dll, out_dir / built_dll.name)


@nox.session(venv_backend="none")
def blender_tests(session: nox.Session) -> None:
    """tests/run_blender_tests.py をラップして実行する。

    引数は tests/run_blender_tests.py にそのまま渡す（--type 等）。

    Examples:
        uvx nox -s blender_tests
        uvx nox -s blender_tests -- --type integration
    """
    executable = _resolve_blender_executable(session)
    session.run(
        str(executable),
        "--background",
        "--factory-startup",
        "--python",
        str(Path(__file__).parent / "tests" / "run_blender_tests.py"),
        "--",
        *session.posargs,
        external=True,
    )


@nox.session(venv_backend="none")
def photoshop_validate(session: nox.Session) -> None:
    """Photoshop UXP プラグインの manifest contract を検証する。"""
    session.run(
        sys.executable,
        "-m",
        "unittest",
        "discover",
        "-s",
        "tests/photoshop",
        "-p",
        "test_*.py",
        external=True,
    )
    session.run(
        "node",
        "--test",
        "tests/photoshop/test_texture_contract.js",
        "tests/photoshop/test_channel_packer.js",
        "tests/photoshop/test_output_folder_store.js",
        external=True,
    )
