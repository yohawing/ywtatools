"""共通ユーティリティのインポート境界を検証する。"""

import ast
from pathlib import Path
import unittest


class CoreImportBoundaryTests(unittest.TestCase):
    """shortcuts.py以外の実装が非推奨ハブへ戻らないことを固定する。"""

    def test_maya_modules_do_not_import_shortcuts(self):
        """Maya実装の実行コードにywta.shortcuts参照を残さない。"""
        ywta_root = Path(__file__).resolve().parents[3] / "maya" / "ywta"
        violations = []
        for path in ywta_root.rglob("*.py"):
            if path.name == "shortcuts.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            shortcut_aliases = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "ywta.shortcuts" or alias.name.startswith("ywta.shortcuts."):
                            violations.append((path, node.lineno, alias.name))
                            shortcut_aliases.add(alias.asname or alias.name.split(".")[-1])
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if module == "ywta.shortcuts" or module.startswith("ywta.shortcuts."):
                        violations.append((path, node.lineno, module))
                        shortcut_aliases.update(alias.asname or alias.name for alias in node.names)
                    elif module == "ywta":
                        for alias in node.names:
                            if alias.name == "shortcuts":
                                violations.append((path, node.lineno, "ywta.shortcuts"))
                                shortcut_aliases.add(alias.asname or alias.name)

            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                    if node.value.id in shortcut_aliases:
                        violations.append((path, node.lineno, "{}.{}".format(node.value.id, node.attr)))

        self.assertEqual([], violations, "非推奨 shortcuts 依存: {}".format(violations))
