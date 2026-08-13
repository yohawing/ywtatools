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


def _add_source_attributes(source):
    """UV seam、color、material、正規化skin weightを追加する。"""
    for name in ("RootMaterial", "TipMaterial"):
        source.data.materials.append(bpy.data.materials.new(name))
    for polygon in source.data.polygons:
        polygon.material_index = polygon.index % 2
    uv_layer = source.data.uv_layers.new(name="HairUV")
    for polygon in source.data.polygons:
        for loop_index in polygon.loop_indices:
            vertex = source.data.loops[loop_index].vertex_index
            uv_layer.data[loop_index].uv = (
                polygon.index * 0.25 + (vertex % 4) * 0.05,
                source.data.vertices[vertex].co.z,
            )
    color = source.data.color_attributes.new(name="HairColor", type="FLOAT_COLOR", domain="POINT")
    for vertex in source.data.vertices:
        color.data[vertex.index].color = (vertex.co.z, 0.25, 1.0 - vertex.co.z, 1.0)

    armature_data = bpy.data.armatures.new("HairRigData")
    armature = bpy.data.objects.new("HairRig", armature_data)
    bpy.context.collection.objects.link(armature)
    bpy.context.view_layer.objects.active = armature
    source.select_set(False)
    armature.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    for name, x in (("RootBone", 0.0), ("TipBone", 0.1)):
        bone = armature_data.edit_bones.new(name)
        bone.head = (x, 0.0, 0.0)
        bone.tail = (x, 0.0, 1.0)
    bpy.ops.object.mode_set(mode="OBJECT")
    modifier = source.modifiers.new(name="HairArmature", type="ARMATURE")
    modifier.object = armature
    root_group = source.vertex_groups.new(name="RootBone")
    tip_group = source.vertex_groups.new(name="TipBone")
    root_group.add(list(range(4)), 1.0, "REPLACE")
    tip_group.add(list(range(4, 8)), 1.0, "REPLACE")
    armature.select_set(False)
    source.select_set(True)
    bpy.context.view_layer.objects.active = source


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
        _add_source_attributes(source)
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
        self.assertEqual(len(generated.data.uv_layers), 1)
        self.assertEqual(len(generated.data.color_attributes), 1)
        self.assertEqual(
            [polygon.material_index for polygon in generated.data.polygons[:4]],
            [0, 1, 0, 1],
        )
        generated_uv = generated.data.uv_layers["HairUV"]
        self.assertAlmostEqual(generated_uv.data[1].uv.x, 0.05)
        self.assertAlmostEqual(generated_uv.data[4].uv.x, 0.30)
        self.assertNotAlmostEqual(generated_uv.data[1].uv.x, generated_uv.data[4].uv.x)
        generated_color = generated.data.color_attributes["HairColor"]
        self.assertAlmostEqual(generated_color.data[4].color[0], 1.0 / 3.0)
        self.assertAlmostEqual(generated_color.data[4].color[2], 2.0 / 3.0)
        root_weight = generated.vertex_groups["RootBone"].weight(4)
        tip_weight = generated.vertex_groups["TipBone"].weight(4)
        self.assertAlmostEqual(root_weight + tip_weight, 1.0)
        self.assertAlmostEqual(root_weight, 2.0 / 3.0)
        curve_names = json.loads(generated["ywta_hair_tube_curve_names"])
        self.assertEqual(len(curve_names), 4)
        first_curve = bpy.data.objects[curve_names[0]]
        first_curve.data.splines[0].points[-1].co.x -= 0.25

        self.assertEqual(bpy.ops.ywta.hair_tube_rebuild(segments=2), {"FINISHED"})
        self.assertEqual((len(generated.data.vertices), len(generated.data.polygons)), (12, 8))
        self.assertLess(generated.data.vertices[8].co.x, -0.5)
        self.assertEqual((len(source.data.vertices), len(source.data.polygons)), (8, 4))
        self.assertEqual(len(generated.data.uv_layers), 1)
        self.assertEqual(len(generated.data.color_attributes), 1)
        self.assertAlmostEqual(
            generated.vertex_groups["RootBone"].weight(4) + generated.vertex_groups["TipBone"].weight(4),
            1.0,
        )

        self.assertEqual(bpy.ops.ywta.hair_tube_generate_lods(segments="1,3"), {"FINISHED"})
        lod1 = bpy.data.objects[f"{generated.name}_LOD1"]
        lod3 = bpy.data.objects[f"{generated.name}_LOD3"]
        self.assertEqual((len(lod1.data.vertices), len(lod1.data.polygons)), (8, 4))
        self.assertEqual((len(lod3.data.vertices), len(lod3.data.polygons)), (16, 12))
        self.assertEqual(len(lod1.data.uv_layers), 1)
        self.assertAlmostEqual(
            lod3.vertex_groups["RootBone"].weight(4) + lod3.vertex_groups["TipBone"].weight(4),
            1.0,
        )
        self.assertEqual(
            lod1["ywta_hair_tube_curve_names"],
            generated["ywta_hair_tube_curve_names"],
        )


if __name__ == "__main__":
    unittest.main()
