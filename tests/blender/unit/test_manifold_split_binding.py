import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "blender" / "modules"))

from ywta_mesh_core import manifold_split  # noqa: E402


class ManifoldSplitBindingTests(unittest.TestCase):
    def test_non_manifold_edge_and_source_mapping(self):
        result = manifold_split.plan(5, [(0, 1, 2), (1, 0, 3), (0, 1, 4)])

        self.assertEqual(result.faces, [(0, 1, 2), (1, 0, 3), (5, 6, 4)])
        self.assertEqual(result.source_vertex_by_output, [0, 1, 2, 3, 4, 0, 1])
        self.assertEqual(result.split_edges, [(0, 1)])
        self.assertTrue(result.changed)

    def test_manifold_input_is_unchanged(self):
        result = manifold_split.plan(4, [(0, 1, 2), (0, 2, 3)])

        self.assertEqual(result.faces, [(0, 1, 2), (0, 2, 3)])
        self.assertFalse(result.changed)


if __name__ == "__main__":
    unittest.main()
