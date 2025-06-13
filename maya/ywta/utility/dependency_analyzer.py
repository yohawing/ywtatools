"""
依存関係分析ツール

このモジュールは、YWTAプロジェクト内のPythonモジュール間の依存関係を分析するための
ツールを提供します。

使用方法:
    import ywta.utility.dependency_analyzer as analyzer

    # 依存関係の分析
    dependencies = analyzer.analyze_dependencies()

    # 循環依存の検出
    cycles = analyzer.detect_cycles(dependencies)

    # 依存関係情報を各モジュールの__init__.pyに追加
    analyzer.update_init_files(dependencies)
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os
import re
import sys
import ast
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)

# YWTAのルートディレクトリ
YWTA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def analyze_dependencies(root_dir=None):
    """
    指定されたディレクトリ内のPythonファイルの依存関係を分析します。

    Args:
        root_dir (str, optional): 分析するディレクトリのパス。デフォルトはYWTAのルートディレクトリ。

    Returns:
        dict: モジュールの依存関係を表す辞書。
              {モジュール名: {依存モジュール名のセット}}
    """
    if root_dir is None:
        root_dir = YWTA_ROOT

    dependencies = defaultdict(set)

    for dirpath, _, filenames in os.walk(root_dir):
        for filename in filenames:
            if filename.endswith(".py"):
                filepath = os.path.join(dirpath, filename)
                module_name = get_module_name(filepath, root_dir)

                if module_name:
                    imports = extract_imports(filepath)
                    # YWTAモジュールのみをフィルタリング
                    ywta_imports = [imp for imp in imports if imp.startswith("ywta.")]
                    if ywta_imports:
                        dependencies[module_name] = set(ywta_imports)

    return dependencies


def get_module_name(filepath, root_dir):
    """
    ファイルパスからPythonモジュール名を取得します。

    Args:
        filepath (str): Pythonファイルのパス
        root_dir (str): ルートディレクトリのパス

    Returns:
        str: モジュール名（例: 'ywta.rig.control'）
    """
    if not filepath.startswith(root_dir):
        return None

    rel_path = os.path.relpath(filepath, os.path.dirname(root_dir))
    module_path = os.path.splitext(rel_path)[0].replace(os.path.sep, ".")

    # __init__.pyの場合はディレクトリ名をモジュール名とする
    if module_path.endswith(".__init__"):
        module_path = module_path[:-9]

    return module_path


def extract_imports(filepath):
    """
    Pythonファイルからインポート文を抽出します。

    Args:
        filepath (str): Pythonファイルのパス

    Returns:
        list: インポートされたモジュール名のリスト
    """
    imports = []

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        tree = ast.parse(content)

        for node in ast.walk(tree):
            # 通常のimport文（import X, import X.Y）
            if isinstance(node, ast.Import):
                for name in node.names:
                    imports.append(name.name)

            # from X import Y形式
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    # 相対インポートの処理
                    if node.level > 0:
                        # 相対インポートは現在のモジュールからの相対パスなので、
                        # 正確な処理は複雑になるため、ここでは単純化
                        module_parts = get_module_name(filepath, YWTA_ROOT).split(".")
                        parent_module = ".".join(module_parts[: -node.level])
                        if node.module != "":
                            full_module = f"{parent_module}.{node.module}"
                        else:
                            full_module = parent_module
                    else:
                        full_module = node.module

                    for name in node.names:
                        if name.name == "*":
                            # import *の場合はモジュール自体を依存関係に追加
                            imports.append(full_module)
                        else:
                            # 通常のfrom importの場合
                            imports.append(full_module)
    except Exception as e:
        logger.error(f"Error parsing {filepath}: {e}")

    return imports


def detect_cycles(dependencies):
    """
    依存関係の循環参照を検出します。

    Args:
        dependencies (dict): モジュールの依存関係を表す辞書

    Returns:
        list: 循環参照のリスト。各循環参照はモジュール名のリスト。
    """
    cycles = []
    visited = set()
    path = []

    def dfs(node):
        if node in path:
            # 循環参照を検出
            cycle_start = path.index(node)
            cycles.append(path[cycle_start:] + [node])
            return

        if node in visited:
            return

        visited.add(node)
        path.append(node)

        for neighbor in dependencies.get(node, []):
            dfs(neighbor)

        path.pop()

    for node in dependencies:
        dfs(node)

    return cycles


def update_init_files(dependencies):
    """
    依存関係情報を各モジュールの__init__.pyファイルに追加します。

    Args:
        dependencies (dict): モジュールの依存関係を表す辞書
    """
    for module, deps in dependencies.items():
        if not deps:
            continue

        # モジュールのディレクトリパスを取得
        parts = module.split(".")
        if len(parts) <= 1:
            continue

        # ywta.category.module -> ywta/category
        module_dir = os.path.join(YWTA_ROOT, *parts[1:-1])
        init_file = os.path.join(module_dir, "__init__.py")

        if not os.path.exists(init_file):
            logger.warning(f"{init_file} が存在しません")
            continue

        # 既存の内容を読み込む
        with open(init_file, "r", encoding="utf-8") as f:
            content = f.read()

        # 依存関係コメントがすでに存在するか確認
        dependency_pattern = r"# Dependencies:.*?(?=\n\n|\Z)"
        if re.search(dependency_pattern, content, re.DOTALL):
            # 既存の依存関係コメントを更新
            updated_content = re.sub(
                dependency_pattern,
                format_dependency_comment(deps),
                content,
                flags=re.DOTALL,
            )
        else:
            # 新しい依存関係コメントを追加
            if content.strip():
                updated_content = (
                    content.rstrip() + "\n\n" + format_dependency_comment(deps) + "\n"
                )
            else:
                updated_content = format_dependency_comment(deps) + "\n"

        # ファイルに書き戻す
        with open(init_file, "w", encoding="utf-8") as f:
            f.write(updated_content)

        logger.info(f"{init_file} の依存関係情報を更新しました")


def format_dependency_comment(deps):
    """
    依存関係コメントをフォーマットします。

    Args:
        deps (set): 依存モジュールのセット

    Returns:
        str: フォーマットされた依存関係コメント
    """
    deps_list = sorted(list(deps))
    comment = "# Dependencies:\n"
    for dep in deps_list:
        comment += f"#   - {dep}\n"
    return comment.rstrip()


def main():
    """
    メイン実行関数。コマンドラインから実行された場合に使用されます。
    """
    import argparse

    parser = argparse.ArgumentParser(description="YWTAモジュールの依存関係を分析します")
    parser.add_argument(
        "--output",
        "-o",
        default="dependencies.dot",
        help="依存関係グラフの出力ファイル（DOT形式）",
    )
    parser.add_argument(
        "--update-init",
        "-u",
        action="store_true",
        help="__init__.pyファイルに依存関係情報を追加します",
    )
    parser.add_argument(
        "--detect-cycles", "-c", action="store_true", help="循環依存を検出します"
    )

    args = parser.parse_args()

    # ログ設定
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # 依存関係の分析
    logger.info("依存関係の分析を開始します...")
    dependencies = analyze_dependencies()

    # 循環依存の検出
    if args.detect_cycles:
        logger.info("循環依存の検出を開始します...")
        cycles = detect_cycles(dependencies)
        if cycles:
            logger.warning(f"{len(cycles)}個の循環依存が検出されました:")
            for i, cycle in enumerate(cycles, 1):
                logger.warning(f"循環{i}: {' -> '.join(cycle)}")
        else:
            logger.info("循環依存は検出されませんでした")

    # __init__.pyの更新
    if args.update_init:
        logger.info("__init__.pyファイルの更新を開始します...")
        update_init_files(dependencies)

    logger.info("依存関係分析が完了しました")


if __name__ == "__main__":
    main()
