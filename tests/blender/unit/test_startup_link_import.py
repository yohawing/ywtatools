"""BlenderのScript Directoryから共有Linkパッケージを解決できることを検証する。"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


_ROOT = Path(__file__).parents[3]
_STARTUP = _ROOT / "blender" / "startup" / "ywtatools_startup.py"
_SPEC = importlib.util.spec_from_file_location("_test_ywtatools_startup", _STARTUP)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"cannot load {_STARTUP}")
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


class BlenderStartupLinkImportTests(unittest.TestCase):
    """起動スクリプトのsys.path所有権とimport境界を検証する。"""

    def setUp(self) -> None:
        """テストごとにsys.pathと共有パッケージの状態を保存する。"""

        _MODULE.unregister()
        self._sys_path = sys.path[:]
        self._link_modules = {
            name: module for name, module in sys.modules.items() if name == "ywta_link" or name.startswith("ywta_link.")
        }

    def tearDown(self) -> None:
        """テストが変更したsys.pathと共有パッケージを復元する。"""

        _MODULE.unregister()
        sys.path[:] = self._sys_path
        for name in list(sys.modules):
            if name == "ywta_link" or name.startswith("ywta_link."):
                del sys.modules[name]
        sys.modules.update(self._link_modules)

    def _remove_project_root_entries(self) -> Path:
        """テスト対象ルートと同値の既存エントリを取り除く。"""

        project_root = Path(_MODULE.__file__).parents[2]
        sys.path[:] = [entry for entry in sys.path if not _MODULE._is_equivalent_path(entry, project_root)]
        return project_root

    def test_register_appends_root_and_imports_shared_package(self) -> None:
        """実際の共有パッケージをScript Directory経由でimportできる。"""

        project_root = self._remove_project_root_entries()
        _MODULE.register()

        project_root_text = str(project_root)
        self.assertEqual(project_root_text, sys.path[-1])
        self.assertEqual(1, sum(entry == project_root_text for entry in sys.path))

        import ywta_link

        self.assertEqual(
            (project_root / "ywta_link" / "__init__.py").resolve(),
            Path(ywta_link.__file__).resolve(),
        )

    def test_register_is_idempotent_and_unregister_removes_owned_entry(self) -> None:
        """registerとunregisterを繰り返してもエントリが増減しすぎない。"""

        project_root = self._remove_project_root_entries()
        _MODULE.register()
        _MODULE.register()
        self.assertEqual(1, sum(_MODULE._is_equivalent_path(entry, project_root) for entry in sys.path))

        _MODULE.unregister()
        self.assertFalse(any(_MODULE._is_equivalent_path(entry, project_root) for entry in sys.path))
        _MODULE.unregister()
        self.assertFalse(any(_MODULE._is_equivalent_path(entry, project_root) for entry in sys.path))

    def test_preexisting_equivalent_entry_is_preserved(self) -> None:
        """既存の同値エントリをregister/unregisterの所有物にしない。"""

        project_root = self._remove_project_root_entries()
        project_root_text = str(project_root)
        sys.path.append(project_root_text)

        _MODULE.register()
        _MODULE.unregister()

        self.assertEqual([project_root_text], [entry for entry in sys.path if entry == project_root_text])

    def test_path_entry_does_not_suppress_owned_string_entry(self) -> None:
        """Pathエントリがあってもimport可能な文字列ルートを追加する。"""

        project_root = self._remove_project_root_entries()
        sys.path.append(project_root)

        _MODULE.register()

        project_root_text = str(project_root)
        self.assertEqual(project_root, sys.path[-2])
        self.assertEqual(project_root_text, sys.path[-1])
        self.assertEqual(project_root_text, _MODULE._owned_project_root)

        import ywta_link

        self.assertEqual(
            (project_root / "ywta_link" / "__init__.py").resolve(),
            Path(ywta_link.__file__).resolve(),
        )

    def test_missing_shared_package_is_a_noop(self) -> None:
        """共有パッケージがない配置ではsys.pathを変更しない。"""

        original = sys.path[:]
        with tempfile.TemporaryDirectory() as temporary_directory:
            missing_startup = Path(temporary_directory) / "blender" / "startup" / "ywtatools_startup.py"
            with patch.object(_MODULE, "__file__", str(missing_startup)):
                _MODULE.register()

        self.assertEqual(original, sys.path)
        self.assertIsNone(_MODULE._owned_project_root)


if __name__ == "__main__":
    unittest.main()
