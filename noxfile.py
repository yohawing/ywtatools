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
