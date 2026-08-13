"""mesh診断ctypesバインディングをBlenderなしで検証する。"""

import os
import sys
import unittest


_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_MODULES_DIR = os.path.join(_REPO_ROOT, "blender", "modules")
if _MODULES_DIR not in sys.path:
    sys.path.insert(0, _MODULES_DIR)

from ywta_mesh_core import mesh_diagnostics  # noqa: E402


class MeshDiagnosticBindingTests(unittest.TestCase):
    """実DLLで診断分類と解放を検証する。"""

    def test_quad_boundary_loop(self):
        report = mesh_diagnostics.diagnose(
            [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)],
            [(0, 1, 2, 3)],
        )
        self.assertEqual(report.issue_count, 0)
        self.assertEqual(report.boundary_loops, [[0, 1, 2, 3]])

    def test_winding_conflict(self):
        report = mesh_diagnostics.diagnose(
            [(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)],
            [(0, 1, 2), (0, 1, 3)],
        )
        self.assertEqual(report.winding_conflict_edges, [(0, 1)])


if __name__ == "__main__":
    unittest.main()
