"""Blender 5.2でHair Tube作成・curve編集・再生成を検証する。"""

import json
import os
import sys
import unittest

import bmesh
import bpy


_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
for path in (
    os.path.join(_REPO_ROOT, "blender", "addons"),
    os.path.join(_REPO_ROOT, "blender", "modules"),
):
    if path not in sys.path:
        sys.path.insert(0, path)

import ywtatools_addon  # noqa: E402


def _make_source():
    """2 stationのopen quad tubeを作る。"""
    vertices = [
        (-0.5, -0.5, 0.0),
        (0.5, -0.5, 0.0),
        (0.5, 0.5, 0.0),
        (-0.5, 0.5, 0.0),
        (-0.5, -0.5, 1.0),
        (0.5, -0.5, 1.0),
        (0.5, 0.5, 1.0),
        (-0.5, 0.5, 1.0),
    ]
    faces = [(0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    mesh = bpy.data.meshes.new("HairTubeSourceMesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new("HairTubeSource", mesh)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    return obj


class HairTubeAddonTests(unittest.TestCase):
    """Hair Tubeの実Blender操作を検証する。"""

    @classmethod
    def setUpClass(cls):
        ywtatools_addon.register()

    @classmethod
    def tearDownClass(cls):
        ywtatools_addon.unregister()

    def test_create_edit_and_rebuild_separate_mesh(self):
        """作成、別object、curve read-back、密度変更を検証する。"""
        source = _make_source()
        bpy.ops.object.mode_set(mode="EDIT")
        bm = bmesh.from_edit_mesh(source.data)
        for edge in bm.edges:
            edge.select = all(vertex.co.z == 0.0 for vertex in edge.verts)
        bmesh.update_edit_mesh(source.data)

        self.assertEqual(bpy.ops.ywta.hair_tube_create(segments=3), {"FINISHED"})
        generated = bpy.context.active_object
        self.assertIsNot(generated, source)
        self.assertEqual((len(source.data.vertices), len(source.data.polygons)), (8, 4))
        self.assertEqual((len(generated.data.vertices), len(generated.data.polygons)), (16, 12))
        curve_names = json.loads(generated["ywta_hair_tube_curve_names"])
        self.assertEqual(len(curve_names), 4)
        first_curve = bpy.data.objects[curve_names[0]]
        first_curve.data.splines[0].points[-1].co.x -= 0.25

        self.assertEqual(bpy.ops.ywta.hair_tube_rebuild(segments=2), {"FINISHED"})
        self.assertEqual((len(generated.data.vertices), len(generated.data.polygons)), (12, 8))
        self.assertLess(generated.data.vertices[8].co.x, -0.5)
        self.assertEqual((len(source.data.vertices), len(source.data.polygons)), (8, 4))

        self.assertEqual(bpy.ops.ywta.hair_tube_generate_lods(segments="1,3"), {"FINISHED"})
        lod1 = bpy.data.objects[f"{generated.name}_LOD1"]
        lod3 = bpy.data.objects[f"{generated.name}_LOD3"]
        self.assertEqual((len(lod1.data.vertices), len(lod1.data.polygons)), (8, 4))
        self.assertEqual((len(lod3.data.vertices), len(lod3.data.polygons)), (16, 12))
        self.assertEqual(
            lod1["ywta_hair_tube_curve_names"],
            generated["ywta_hair_tube_curve_names"],
        )


if __name__ == "__main__":
    unittest.main()
