"""Volume Preserving Smooth Edit Modeオペレータの実Blenderテスト。"""

import os
import sys
import unittest

import bpy


_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", "..", ".."))
for path in (
    os.path.join(_REPO_ROOT, "blender", "modules"),
    os.path.join(_REPO_ROOT, "blender", "addons", "ywtatools_addon"),
):
    if path not in sys.path:
        sys.path.insert(0, path)

import volume_smoothing  # noqa: E402


def _signed_volume(vertices, triangles):
    """オペレータとRust実装から独立して符号付き体積を計算する。"""
    volume = 0.0
    for triangle in triangles:
        a, b, c = (vertices[index] for index in triangle)
        volume += a.dot(b.cross(c)) / 6.0
    return volume


class VolumeSmoothingOperatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        volume_smoothing.register()

    @classmethod
    def tearDownClass(cls):
        volume_smoothing.unregister()

    def setUp(self):
        bpy.ops.object.mode_set(mode="OBJECT") if bpy.context.object else None
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.object.delete(use_global=False)

    def _create_edit_mesh(self, name, vertices, faces):
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(vertices, [], faces)
        mesh.update()
        obj = bpy.data.objects.new(name, mesh)
        bpy.context.collection.objects.link(obj)
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        return obj

    def test_closed_mesh_preserves_oracle_volume(self):
        obj = self._create_edit_mesh(
            "ClosedTetra",
            [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 3.0, 0.0), (0.0, 0.0, 4.0)],
            [(0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3)],
        )
        bpy.ops.object.mode_set(mode="OBJECT")
        obj.data.calc_loop_triangles()
        before_positions = [vertex.co.copy() for vertex in obj.data.vertices]
        triangles = [tuple(triangle.vertices) for triangle in obj.data.loop_triangles]
        before_volume = _signed_volume(before_positions, triangles)
        bpy.ops.object.mode_set(mode="EDIT")

        result = bpy.ops.ywta.volume_smooth(
            mode="HC",
            iterations=2,
            preserve_volume=True,
            preserve_boundary=False,
        )
        self.assertEqual(result, {"FINISHED"})

        bpy.ops.object.mode_set(mode="OBJECT")
        after_positions = [vertex.co.copy() for vertex in obj.data.vertices]
        after_volume = _signed_volume(after_positions, triangles)
        # Blenderの頂点座標はfloat32へ格納されるため、DLLのf64結果より丸め誤差が増える。
        self.assertLess(abs(after_volume - before_volume), abs(before_volume) * 5.0e-7)
        self.assertTrue(any((after - before).length > 1.0e-6 for before, after in zip(before_positions, after_positions)))

    def test_open_mesh_falls_back_without_volume_error(self):
        self._create_edit_mesh(
            "OpenQuad",
            [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (2.0, 1.0, 0.3), (0.0, 1.0, 0.0)],
            [(0, 1, 2, 3)],
        )
        result = bpy.ops.ywta.volume_smooth(
            mode="HC",
            iterations=1,
            preserve_volume=True,
            preserve_boundary=False,
        )
        self.assertEqual(result, {"FINISHED"})


if __name__ == "__main__":
    unittest.main()
