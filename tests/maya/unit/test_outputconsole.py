"""OutputConsoleのQt互換importと色分けを検証する。"""

import unittest

from ywta.ui.widgets.outputconsole import OutputConsole


class OutputConsoleTests(unittest.TestCase):
    def test_import_resolves_available_maya_qt_binding(self):
        self.assertEqual(OutputConsole.__name__, "OutputConsole")
        self.assertEqual(OutputConsole.normal_color.red(), 200)


if __name__ == "__main__":
    unittest.main()
