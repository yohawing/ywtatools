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

import sys

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
