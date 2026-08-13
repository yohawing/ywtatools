"""安全mesh修復plan bindingを実DLLで検証する。"""

import os
import sys
import unittest


_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_MODULES_DIR = os.path.join(_REPO_ROOT, "blender", "modules")
if _MODULES_DIR not in sys.path:
    sys.path.insert(0, _MODULES_DIR)

from ywta_mesh_core import mesh_repair  # noqa: E402


class MeshRepairBindingTests(unittest.TestCase):
    def test_removal_mapping(self):
        repair = mesh_repair.plan(
            [(0, 0, 0), (1, 0, 0), (0, 1, 0), (2, 0, 0)],
            [(0, 1, 3), (0, 1, 2), (2, 1, 0)],
        )
        self.assertEqual(repair.old_face_to_new, [None, 0, None])
        self.assertEqual(repair.removed_zero_area_faces, [0])
        self.assertEqual(repair.removed_duplicate_faces, [2])


if __name__ == "__main__":
    unittest.main()
