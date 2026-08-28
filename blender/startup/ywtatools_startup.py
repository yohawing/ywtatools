"""Blender起動時にYWTA Toolsの共有Pythonパッケージを解決する。"""

from __future__ import annotations

import sys
from pathlib import Path


_owned_project_root: str | None = None


def _is_equivalent_path(entry: object, project_root: Path) -> bool:
    """sys.pathのエントリがプロジェクトルートと同じ場所か判定する。"""

    # CPythonのimport機構はsys.path内のPathLikeを検索パスとして扱わない。
    if not isinstance(entry, str):
        return False

    try:
        return Path(entry).resolve(strict=False) == project_root.resolve(strict=False)
    except (OSError, RuntimeError, TypeError, ValueError):
        return False


def _resolve_project_root() -> Path | None:
    """起動スクリプトからプロジェクトルートを求める。"""

    try:
        return Path(__file__).parents[2]
    except (IndexError, OSError, RuntimeError, TypeError, ValueError):
        return None


def register() -> None:
    """共有パッケージをimportできるよう、必要な場合だけルートを追加する。"""

    global _owned_project_root

    project_root = _resolve_project_root()
    if project_root is None:
        return

    try:
        package_init = project_root / "ywta_link" / "__init__.py"
        if not package_init.is_file():
            return
        if any(_is_equivalent_path(entry, project_root) for entry in sys.path):
            return

        project_root_text = str(project_root)
        sys.path.append(project_root_text)
        _owned_project_root = project_root_text
    except (OSError, RuntimeError, TypeError, ValueError):
        return


def unregister() -> None:
    """registerで追加したルートだけを、再実行可能な形で取り除く。"""

    global _owned_project_root

    if _owned_project_root is None:
        return

    project_root = _owned_project_root
    _owned_project_root = None
    try:
        sys.path.remove(project_root)
    except ValueError:
        pass


if __name__ == "__main__":
    print("startup YWTATools: 2024 yohawing")
    register()
