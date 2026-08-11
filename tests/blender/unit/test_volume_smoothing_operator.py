"""Volume Preserving Smooth Edit Modeオペレータの実Blenderテスト。"""

import os
import sys
import unittest
from unittest import mock

import bmesh
import bpy
from mathutils import Matrix, Vector


_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", "..", ".."))
for path in (
    os.path.join(_REPO_ROOT, "blender", "modules"),
    os.path.join(_REPO_ROOT, "blender", "addons", "ywtatools_addon"),
):
    if path not in sys.path:
        sys.path.insert(0, path)

import volume_smoothing  # noqa: E402
from ywta_mesh_smoothing import binding  # noqa: E402


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

    def test_geodesic_falloff_does_not_reach_disconnected_back_surface(self):
        bm = bmesh.new()
        try:
            front = [bm.verts.new(coordinate) for coordinate in [(0, 0, 0), (1, 0, 0), (0, 1, 0)]]
            back = [bm.verts.new(coordinate) for coordinate in [(0, 0, 0.01), (1, 0, 0.01), (0, 1, 0.01)]]
            bm.faces.new(front)
            bm.faces.new(back)
            bm.verts.ensure_lookup_table()
            bm.faces.ensure_lookup_table()
            bm.verts.index_update()
            bm.faces.index_update()

            weights = volume_smoothing._geodesic_brush_weights(
                bm,
                0,
                Vector((0.2, 0.2, 0.0)),
                Matrix.Identity(4),
                radius=2.0,
                strength=1.0,
                use_selection_mask=False,
                preserve_boundary=False,
            )

            self.assertTrue(any(weight > 0.0 for weight in weights[:3]))
            self.assertEqual(weights[3:], [0.0, 0.0, 0.0])
        finally:
            bm.free()

    def test_brush_solver_moves_weighted_vertices_through_release_dll(self):
        bm = bmesh.new()
        try:
            vertices = [bm.verts.new(coordinate) for coordinate in [(0, 0, 0), (2, 0, 0), (0, 1, 0.4)]]
            bm.faces.new(vertices)
            bm.verts.ensure_lookup_table()
            bm.verts.index_update()
            bm.normal_update()
            edges = [index for edge in bm.edges for index in (edge.verts[0].index, edge.verts[1].index)]
            session = binding.MeshSmoothingSession(3, edges)
            before = [vertex.co.copy() for vertex in bm.verts]

            volume_smoothing._apply_brush_solver(
                bm,
                session,
                [1.0, 0.5, 0.25],
                "SMOOTH",
                False,
                1,
            )

            self.assertTrue(any((after.co - start).length > 1.0e-6 for after, start in zip(bm.verts, before)))
        finally:
            bm.free()

    def test_vertex_group_is_continuous_mask_for_normal_operator(self):
        """指定Vertex Groupの連続ウェイトを通常オペレータへ渡す。"""
        obj = self._create_edit_mesh(
            "WeightedMask",
            [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 1.0, 0.5)],
            [(0, 1, 2)],
        )
        bpy.ops.object.mode_set(mode="OBJECT")
        group = obj.vertex_groups.new(name="SmoothingMask")
        group.add([0, 1, 2], 0.0, "REPLACE")
        group.add([0], 1.0, "REPLACE")
        group.add([1], 0.5, "REPLACE")
        obj.vertex_groups.active_index = group.index
        bpy.ops.object.mode_set(mode="EDIT")

        captured = {}

        def fake_smooth(positions, _edges, **kwargs):
            captured.update(kwargs)
            return list(positions)

        with mock.patch.object(volume_smoothing.binding, "smooth", side_effect=fake_smooth):
            result = bpy.ops.ywta.volume_smooth(
                mode="HC",
                iterations=1,
                preserve_volume=False,
                preserve_boundary=False,
                preserve_rails=False,
                mask_vertex_group="SmoothingMask",
            )

        self.assertEqual(result, {"FINISHED"})
        self.assertEqual(captured["vertex_weights"], [1.0, 0.5, 0.0])

    def test_empty_vertex_group_falls_back_to_current_selection(self):
        """空欄のVertex Group指定では現在の頂点選択をマスクにする。"""
        obj = self._create_edit_mesh(
            "EmptyMask",
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
            [(0, 1, 2)],
        )
        bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="DESELECT")
        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        bm.verts[0].select = True
        bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)

        captured = {}

        def fake_smooth(positions, _edges, **kwargs):
            captured.update(kwargs)
            return list(positions)

        with mock.patch.object(volume_smoothing.binding, "smooth", side_effect=fake_smooth):
            result = bpy.ops.ywta.volume_smooth(
                mode="HC",
                iterations=1,
                preserve_volume=False,
                preserve_boundary=False,
                preserve_rails=False,
            )

        self.assertEqual(result, {"FINISHED"})
        self.assertEqual(captured["vertex_weights"], [1.0, 0.0, 0.0])

    def test_edge_selection_uses_full_mask_and_preserves_selected_rail(self):
        """空のVertex GroupとEDGE選択では全頂点をmaskにし、選択edgeをrailにする。"""
        self._create_edit_mesh(
            "EdgeMask",
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)],
            [(0, 1, 2, 3)],
        )
        tool_settings = bpy.context.tool_settings
        previous_mode = tuple(tool_settings.mesh_select_mode)
        try:
            tool_settings.mesh_select_mode = (False, True, False)
            bpy.ops.mesh.select_all(action="DESELECT")
            bm = bmesh.from_edit_mesh(bpy.context.object.data)
            bm.edges.ensure_lookup_table()
            bm.edges[0].select = True
            bmesh.update_edit_mesh(bpy.context.object.data, loop_triangles=False, destructive=False)

            captured = {}

            def fake_smooth(positions, _edges, **kwargs):
                captured.update(kwargs)
                return list(positions)

            with mock.patch.object(volume_smoothing.binding, "smooth", side_effect=fake_smooth):
                result = bpy.ops.ywta.volume_smooth(
                    mode="HC",
                    iterations=1,
                    preserve_volume=False,
                    preserve_boundary=False,
                    preserve_rails=True,
                )
        finally:
            tool_settings.mesh_select_mode = previous_mode

        self.assertEqual(result, {"FINISHED"})
        self.assertEqual(captured["vertex_weights"], [1.0, 1.0, 1.0, 1.0])
        self.assertEqual(captured["constraint_modes"].count(binding.CONSTRAINT_FIXED), 2)
        self.assertEqual(captured["constraint_modes"].count(binding.CONSTRAINT_FREE), 2)

    def test_named_empty_vertex_group_cancels_without_selection_fallback(self):
        """指定済みの空Vertex Groupはゼロmaskとして安全にキャンセルする。"""
        obj = self._create_edit_mesh(
            "NamedEmptyMask",
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
            [(0, 1, 2)],
        )
        bpy.ops.object.mode_set(mode="OBJECT")
        group = obj.vertex_groups.new(name="NamedEmptyGroup")
        bpy.ops.object.mode_set(mode="EDIT")
        result = bpy.ops.ywta.volume_smooth(
            mode="HC",
            iterations=1,
            preserve_volume=False,
            preserve_boundary=False,
            preserve_rails=False,
            mask_vertex_group=group.name,
        )
        self.assertEqual(result, {"CANCELLED"})

    def test_rail_chain_classifies_interior_and_fixed_endpoints(self):
        """直線railの内部を接線制約にし、端点・分岐・cornerを固定する。"""
        bm = bmesh.new()
        try:
            vertices = [bm.verts.new(coordinate) for coordinate in [(-1, 0, 0), (0, 0, 0), (1, 0, 0)]]
            first = bm.edges.new((vertices[0], vertices[1]))
            second = bm.edges.new((vertices[1], vertices[2]))
            first.seam = True
            second.seam = True
            bm.verts.ensure_lookup_table()
            bm.edges.ensure_lookup_table()
            bm.verts.index_update()

            modes, directions = volume_smoothing._rail_constraints(bm, include_selected_edges=False)
            self.assertEqual(modes[1], binding.CONSTRAINT_RAIL_LINE)
            self.assertEqual(modes[0], binding.CONSTRAINT_FIXED)
            self.assertEqual(modes[2], binding.CONSTRAINT_FIXED)
            self.assertAlmostEqual(abs(directions[1].dot(Vector((1.0, 0.0, 0.0)))), 1.0, places=6)

            branch = bm.verts.new((0, 1, 0))
            branch_edge = bm.edges.new((vertices[1], branch))
            branch_edge.seam = True
            bm.verts.ensure_lookup_table()
            bm.edges.ensure_lookup_table()
            bm.verts.index_update()
            modes, _directions = volume_smoothing._rail_constraints(bm, include_selected_edges=False)
            self.assertEqual(modes[1], binding.CONSTRAINT_FIXED)
        finally:
            bm.free()

    def test_hard_crease_seam_and_edge_selection_are_rail_candidates(self):
        """hard edge、crease、seam、EDGE選択をrail候補として認識する。"""
        bm = bmesh.new()
        try:
            crease_layer = bm.edges.layers.float.new("crease_edge")
            vertices = [bm.verts.new((index, 0, 0)) for index in range(8)]
            hard = bm.edges.new((vertices[0], vertices[1]))
            bm.faces.new((vertices[0], vertices[1], vertices[2]))
            bm.faces.new((vertices[1], vertices[0], vertices[3]))
            seam = bm.edges.new((vertices[2], vertices[3]))
            crease = bm.edges.new((vertices[4], vertices[5]))
            selected = bm.edges.new((vertices[6], vertices[7]))
            hard.smooth = False
            seam.seam = True
            crease[crease_layer] = 1.0
            selected.select = True
            self.assertTrue(volume_smoothing._edge_is_rail_candidate(hard, crease_layer, False))
            self.assertTrue(volume_smoothing._edge_is_rail_candidate(seam, crease_layer, False))
            self.assertTrue(volume_smoothing._edge_is_rail_candidate(crease, crease_layer, False))
            self.assertTrue(volume_smoothing._edge_is_rail_candidate(selected, crease_layer, True))
            self.assertFalse(volume_smoothing._edge_is_rail_candidate(selected, crease_layer, False))
        finally:
            bm.free()

    def test_face_selection_with_seam_preserves_panel_rail(self):
        """Face選択時でもseamのpanel線をrail候補として保持する。"""
        bm = bmesh.new()
        try:
            vertices = [
                bm.verts.new((0, 0, 0)),
                bm.verts.new((1, 0, 0)),
                bm.verts.new((2, 0, 0)),
            ]
            bm.faces.new((vertices[0], vertices[1], vertices[2]))
            bm.verts.ensure_lookup_table()
            bm.edges.ensure_lookup_table()
            bm.faces.ensure_lookup_table()
            bm.verts.index_update()
            bm.faces.index_update()
            seam = next(edge for edge in bm.edges if set(edge.verts) == {vertices[0], vertices[1]})
            seam.seam = True
            bm.faces[0].select = True
            modes, directions = volume_smoothing._rail_constraints(bm, include_selected_edges=False)
            self.assertIn(modes[0], {binding.CONSTRAINT_FIXED, binding.CONSTRAINT_RAIL_LINE})
            self.assertIn(modes[1], {binding.CONSTRAINT_FIXED, binding.CONSTRAINT_RAIL_LINE})
            self.assertTrue(any(direction.length > 0.0 for direction in directions[:2]))
        finally:
            bm.free()


if __name__ == "__main__":
    unittest.main()
