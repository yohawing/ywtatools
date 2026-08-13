"""AutoRemeshの保持元と再生成フローを実Blender Objectで検証する。"""

import os
import sys
import unittest
from unittest import mock

import bpy


_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
for path in (os.path.join(_REPO_ROOT, "blender", "addons"), os.path.join(_REPO_ROOT, "blender", "modules")):
    if path not in sys.path:
        sys.path.insert(0, path)

import ywtatools_addon  # noqa: E402
from ywtatools_addon import autoremesher  # noqa: E402


class AutoRemesherAddonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ywtatools_addon.register()

    @classmethod
    def tearDownClass(cls):
        ywtatools_addon.unregister()

    def setUp(self):
        bpy.ops.object.mode_set(mode="OBJECT") if bpy.context.active_object else None
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.object.delete(use_global=False)

    def test_archives_source_and_updates_same_output(self):
        mesh = bpy.data.meshes.new("AutoRemeshSourceMesh")
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
        source = bpy.data.objects.new("AutoRemeshSource", mesh)
        bpy.context.collection.objects.link(source)
        source.select_set(True)
        bpy.context.view_layer.objects.active = source

        with mock.patch.object(
            autoremesher.binding,
            "remesh",
            side_effect=[
                ([0, 0, 0, 1, 0, 0, 0, 1, 0], [(0, 1, 2)]),
                ([0, 0, 0, 2, 0, 0, 0, 2, 0, 2, 2, 0], [(0, 1, 2, 3)]),
            ],
        ):
            self.assertEqual(bpy.ops.ywta.autoremesh(target_count=100), {"FINISHED"})
            output = bpy.context.active_object
            self.assertIs(output.ywta_autoremesh_source, source)
            archive = bpy.data.collections["YWTA AutoRemesh Sources"]
            self.assertTrue(archive.hide_viewport)
            self.assertTrue(archive.hide_render)
            self.assertIn(source, archive.objects.values())
            self.assertEqual(len([obj for obj in bpy.data.objects if obj.name.startswith("AutoRemeshSource_remeshed")]), 1)

            self.assertEqual(bpy.ops.ywta.autoremesh(target_count=200), {"FINISHED"})
            self.assertIs(bpy.context.active_object, output)
            self.assertEqual(len(output.data.vertices), 4)
            self.assertEqual(output["ywta_autoremesh_target_count"], 200)
            self.assertEqual(len([obj for obj in bpy.data.objects if obj.name.startswith("AutoRemeshSource_remeshed")]), 1)

            self.assertEqual(bpy.ops.ywta.reveal_autoremesh_source(), {"FINISHED"})
            self.assertIs(bpy.context.active_object, source)
            self.assertFalse(archive.hide_viewport)


if __name__ == "__main__":
    unittest.main()
