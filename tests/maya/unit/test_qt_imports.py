"""主要UIモジュールが利用可能なMaya Qt bindingでimportできることを検証する。"""

import importlib
import unittest


class QtImportTests(unittest.TestCase):
    def test_ui_modules_import_without_fixed_pyside_version(self):
        modules = (
            "ywta.pipeline.runscript",
            "ywta.ui.stringcache",
            "ywta.ui.widgets.mayanodewidget",
            "ywta.ui.widgets.accordionwidget",
            "ywta.anim.ikrig",
        )
        for name in modules:
            with self.subTest(module=name):
                self.assertIsNotNone(importlib.import_module(name))


if __name__ == "__main__":
    unittest.main()
