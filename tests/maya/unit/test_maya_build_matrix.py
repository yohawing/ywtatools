"""Maya C++プラグインのビルド対象行列を検証する純Pythonテスト。"""

from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _load_noxfile_without_nox() -> types.ModuleType:
    """nox本体を起動せず、純粋なバージョン解決ヘルパーだけ読み込む。"""
    fake_nox = types.ModuleType("nox")
    fake_nox.options = types.SimpleNamespace(sessions=[])

    def session_decorator(*_args, **_kwargs):
        def decorate(function):
            return function

        return decorate

    fake_nox.session = session_decorator
    previous_nox = sys.modules.get("nox")
    sys.modules["nox"] = fake_nox
    try:
        module_name = "ywtatools_test_noxfile"
        spec = importlib.util.spec_from_file_location(module_name, REPOSITORY_ROOT / "noxfile.py")
        if spec is None or spec.loader is None:
            raise RuntimeError("noxfile.pyのロード仕様を作成できません")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if previous_nox is None:
            sys.modules.pop("nox", None)
        else:
            sys.modules["nox"] = previous_nox


class TestMayaBuildMatrix(unittest.TestCase):
    """ビルド対象の既定値と引数検証を確認する。"""

    @classmethod
    def setUpClass(cls):
        cls.noxfile = _load_noxfile_without_nox()

    def test_default_versions_are_current_supported_matrix(self):
        self.assertEqual(self.noxfile.MAYA_PLUGIN_VERSIONS, (2025, 2026, 2027))
        self.assertEqual(self.noxfile._resolve_maya_plugin_versions(()), (2025, 2026, 2027))

    def test_explicit_versions_are_passed_through_in_order(self):
        resolve = self.noxfile._resolve_maya_plugin_versions
        self.assertEqual(resolve(("2027",)), (2027,))
        self.assertEqual(resolve(("2025", "2027")), (2025, 2027))

    def test_invalid_versions_are_rejected(self):
        resolve = self.noxfile._resolve_maya_plugin_versions
        for invalid in (("2024",), ("maya",), ("+2025",), ("2025.0",)):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                resolve(invalid)

    def test_build_script_contract(self):
        script = (REPOSITORY_ROOT / "maya" / "cpp" / "build.bat").read_text(encoding="utf-8")
        lowered = script.lower()
        for version in ("2025", "2026", "2027"):
            self.assertIn(f'call :build_version "{version}"', lowered)
            self.assertIn(f'if "%version%"=="{version}"', lowered)
        self.assertIn("cmake -s", lowered)
        self.assertIn("cmake --build", lowered)
        self.assertIn("if errorlevel 1", lowered)
        self.assertNotIn("del ", lowered)


if __name__ == "__main__":
    unittest.main()
