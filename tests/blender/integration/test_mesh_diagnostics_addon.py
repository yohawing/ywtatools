"""Blenderでmesh診断結果のcomponent選択を検証する。"""

import os
import json
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
        self.assertEqual(bpy.ops.ywta.safe_mesh_repair(apply_changes=True), {"FINISHED"})
        bpy.ops.object.mode_set(mode="OBJECT")
        first = tuple(mesh.polygons[0].vertices)
        second = tuple(mesh.polygons[1].vertices)

        def direction(face):
            for index, vertex in enumerate(face):
                following = face[(index + 1) % len(face)]
                if {vertex, following} == {0, 1}:
                    return vertex == 0
            return None

        self.assertNotEqual(direction(first), direction(second))

    def test_safe_repair_dry_run_and_apply(self):
        bpy.ops.object.mode_set(mode="OBJECT")
        mesh = bpy.data.meshes.new("RepairMesh")
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0), (2, 0, 0)], [], [(0, 1, 3), (0, 1, 2)])
        mesh.materials.append(bpy.data.materials.new("RemovedMaterial"))
        mesh.materials.append(bpy.data.materials.new("KeptMaterial"))
        mesh.polygons[1].material_index = 1
        uv_layer = mesh.uv_layers.new(name="RepairUV")
        for index, datum in enumerate(uv_layer.data):
            datum.uv = (index / 10.0, 0.5)
        obj = bpy.data.objects.new("RepairObject", mesh)
        bpy.context.collection.objects.link(obj)
        for selected in bpy.context.selected_objects:
            selected.select_set(False)
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj

        self.assertEqual(bpy.ops.ywta.safe_mesh_repair(apply_changes=False), {"FINISHED"})
        self.assertEqual(len(obj.data.polygons), 2)
        self.assertEqual(bpy.ops.ywta.safe_mesh_repair(apply_changes=True), {"FINISHED"})
        bpy.ops.object.mode_set(mode="OBJECT")
        self.assertEqual(len(obj.data.polygons), 1)
        self.assertEqual(obj.data.polygons[0].material_index, 1)
        self.assertEqual(len(obj.data.uv_layers["RepairUV"].data), 3)
        self.assertEqual(json.loads(obj["ywta_mesh_repair_old_face_to_new"]), [None, 0])


if __name__ == "__main__":
    unittest.main()
