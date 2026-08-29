"""MayaモジュールのPython検索パス契約を検証する。"""

import ast
from pathlib import Path
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _module_block(text: str, version: str) -> str:
    """指定したMayaバージョンのmodule定義部分を返す。"""
    marker = "+ MAYAVERSION:{} ".format(version)
    start = text.index(marker)
    next_block = text.find("\n+ MAYAVERSION:", start + len(marker))
    return text[start:] if next_block == -1 else text[start:next_block]


class MayaModuleInstallTests(unittest.TestCase):
    """リポジトリ外の作業ディレクトリでも共通基盤を解決できることを確認する。"""

    def test_supported_module_blocks_include_maya_and_repository_paths(self):
        """Mayaコードとリポジトリ直下のywta_linkを両方検索対象にする。"""
        module_text = (REPOSITORY_ROOT / "ywtatools.mod").read_text(encoding="utf-8")

        for version in ("2022", "2024"):
            with self.subTest(version=version):
                block = _module_block(module_text, version)
                path_lines = [
                    line.strip()
                    for line in block.splitlines()
                    if line.strip().startswith("PYTHONPATH")
                ]
                self.assertEqual(
                    ["PYTHONPATH +:= .", "PYTHONPATH +:= .."],
                    path_lines,
                )

    def test_maya_runner_uses_isolated_application_directory(self):
        """テスト実行時のcwdを一時Maya設定ディレクトリへ固定する。"""
        runner_path = REPOSITORY_ROOT / "tests" / "run_maya_tests.py"
        runner_tree = ast.parse(runner_path.read_text(encoding="utf-8"))
        calls = [
            node
            for node in ast.walk(runner_tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "check_call"
        ]
        self.assertEqual(1, len(calls))
        self.assertTrue(
            any(keyword.arg == "cwd" and isinstance(keyword.value, ast.Name)
                and keyword.value.id == "maya_app_dir"
                for keyword in calls[0].keywords)
        )


if __name__ == "__main__":
    unittest.main()
