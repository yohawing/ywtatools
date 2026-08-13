"""Blenderでmesh診断結果のcomponent選択を検証する。"""

import os
import sys
import unittest

import bmesh
import bpy


_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
for path in (os.path.join(_REPO_ROOT, "blender", "addons"), os.path.join(_REPO_ROOT, "blender", "modules")):
    if path not in sys.path:
        sys.path.insert(0, path)

import ywtatools_addon  # noqa: E402


class MeshDiagnosticsAddonTests(unittest.TestCase):
    """実Blenderの選択反映を検証する。"""

    @classmethod
    def setUpClass(cls):
        ywtatools_addon.register()

    @classmethod
    def tearDownClass(cls):
        ywtatools_addon.unregister()

    def test_selects_winding_conflict_edge(self):
        mesh = bpy.data.meshes.new("DiagnosticMesh")
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)], [], [(0, 1, 2), (0, 1, 3)])
        obj = bpy.data.objects.new("DiagnosticObject", mesh)
        bpy.context.collection.objects.link(obj)
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)

        self.assertEqual(bpy.ops.ywta.select_mesh_diagnostics(issue="WINDING"), {"FINISHED"})
        bm = bmesh.from_edit_mesh(mesh)
        selected = [tuple(sorted(vertex.index for vertex in edge.verts)) for edge in bm.edges if edge.select]
        self.assertEqual(selected, [(0, 1)])


if __name__ == "__main__":
    unittest.main()
