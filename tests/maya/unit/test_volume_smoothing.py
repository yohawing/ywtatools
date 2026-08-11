"""Maya 2024上のRust Volume Smoothingコマンド統合テスト。"""

from __future__ import annotations

import math
from pathlib import Path
import unittest
from unittest import mock

import maya.api.OpenMaya as om2
import maya.cmds as cmds

from ywta.mesh.volume_smoothing import (
    VolumeSmoothingBrushContext,
    _apply_rail_constraints,
    _geodesic_brush_weights,
    _mesh_rail_edges,
    _shape_selection,
    activate_volume_smooth_brush,
)


_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_PLUGIN_PATH = _REPOSITORY_ROOT / "maya" / "plug-ins" / "ywtaVolumeSmoothing.py"
_DLL_PATH = _REPOSITORY_ROOT / "bin" / "windows" / "ywta_mesh_smoothing.dll"


def _load_smoothing_plugin() -> bool:
    """テスト対象のPythonプラグインをロードする。"""
    if not _DLL_PATH.exists():
        return False
    try:
        cmds.loadPlugin(str(_PLUGIN_PATH), quiet=True)
    except RuntimeError:
        # 既にロード済みの場合はそのまま利用する。
        pass
    try:
        return bool(cmds.pluginInfo("ywtaVolumeSmoothing.py", query=True, loaded=True))
    except RuntimeError:
        return False


PLUGIN_AVAILABLE = _load_smoothing_plugin()


def _points(shape):
    """メッシュのobject-space座標を比較可能なtuple列で返す。"""
    selection = om2.MSelectionList()
    selection.add(shape)
    dag_path = selection.getDagPath(0)
    return tuple(
        (float(point.x), float(point.y), float(point.z)) for point in om2.MFnMesh(dag_path).getPoints(om2.MSpace.kObject)
    )


def _maya_triangles(shape):
    """Mayaが現在の面に割り当てた三角形インデックスを返す。"""
    selection = om2.MSelectionList()
    selection.add(shape)
    dag_path = selection.getDagPath(0)
    mesh_fn = om2.MFnMesh(dag_path)
    _triangle_counts, triangle_indices = mesh_fn.getTriangles()
    return tuple(int(index) for index in triangle_indices)


def _signed_volume(shape, triangles):
    """独立に取得したMaya実三角化から符号付き体積を計算する。"""
    selection = om2.MSelectionList()
    selection.add(shape)
    dag_path = selection.getDagPath(0)
    points = om2.MFnMesh(dag_path).getPoints(om2.MSpace.kObject)
    volume = 0.0
    for offset in range(0, len(triangles), 3):
        a, b, c = (points[triangles[offset]], points[triangles[offset + 1]], points[triangles[offset + 2]])
        volume += (a.x * (b.y * c.z - b.z * c.y) + a.y * (b.z * c.x - b.x * c.z) + a.z * (b.x * c.y - b.y * c.x)) / 6.0
    return volume


@unittest.skipUnless(PLUGIN_AVAILABLE, "MayaプラグインまたはRust DLLが利用できません")
class TestVolumeSmoothing(unittest.TestCase):
    """実Mayaでのメッシュ変更、体積、Undo/Redo、選択範囲を検証する。"""

    def setUp(self):
        cmds.file(new=True, force=True)

    def tearDown(self):
        cmds.file(new=True, force=True)

    def test_closed_mesh_preserves_signed_volume_and_undo_redo(self):
        cube, _ = cmds.polyCube(name="volumeCube")
        shape = cmds.listRelatives(cube, shapes=True, noIntermediate=True)[0]
        cmds.xform(f"{shape}.vtx[0]", objectSpace=True, translation=(-0.7, -0.4, -0.2))
        triangles = _maya_triangles(shape)
        before = _points(shape)
        before_volume = _signed_volume(shape, triangles)

        cmds.select(cube, replace=True)
        cmds.ywtaVolumeSmooth(preserveRails=False)
        after = _points(shape)
        after_volume = _signed_volume(shape, triangles)

        self.assertNotEqual(before, after)
        self.assertTrue(math.isclose(before_volume, after_volume, rel_tol=1.0e-7, abs_tol=1.0e-8))

        cmds.undo()
        self.assertEqual(_points(shape), before)
        cmds.redo()
        self.assertEqual(_points(shape), after)

    def test_partial_vertex_selection_keeps_unselected_and_boundary_fixed(self):
        mesh, _ = cmds.polyPlane(name="partialPlane", subdivisionsX=4, subdivisionsY=4)
        shape = cmds.listRelatives(mesh, shapes=True, noIntermediate=True)[0]
        # 中央頂点を法線方向へずらし、周囲の3x3領域だけを選択する。
        cmds.xform(f"{shape}.vtx[12]", objectSpace=True, translation=(0.0, 0.0, 1.0))
        before = _points(shape)
        selected = [6, 7, 8, 11, 12, 13, 16, 17, 18]
        cmds.select([f"{shape}.vtx[{index}]" for index in selected], replace=True)
        cmds.ywtaVolumeSmooth()
        after = _points(shape)

        self.assertNotEqual(before[12], after[12])
        for index in range(len(before)):
            if index not in {12}:
                self.assertEqual(before[index], after[index])

    def test_face_selection_smooths_only_panel_interior(self):
        """面選択を頂点マスクへ変換し、選択境界を崩さず内側だけ均す。"""
        mesh, _ = cmds.polyPlane(name="facePanelPlane", subdivisionsX=4, subdivisionsY=4)
        shape = cmds.listRelatives(mesh, shapes=True, noIntermediate=True)[0]
        cmds.xform(f"{shape}.vtx[12]", objectSpace=True, translation=(0.0, 0.0, 1.0))
        before = _points(shape)
        cmds.select([f"{shape}.f[{index}]" for index in (5, 6, 9, 10)], replace=True)

        cmds.ywtaVolumeSmooth(preserveRails=False)
        after = _points(shape)

        self.assertNotEqual(before[12], after[12])
        for index in range(len(before)):
            if index != 12:
                self.assertEqual(before[index], after[index])

    def test_closed_partial_selection_preserves_volume(self):
        """閉メッシュの部分選択でも固定点を保ったまま体積を補正する。"""
        mesh, _ = cmds.polySphere(name="partialVolumeSphere", subdivisionsX=12, subdivisionsY=8)
        shape = cmds.listRelatives(mesh, shapes=True, noIntermediate=True)[0]
        vertex_count = cmds.polyEvaluate(shape, vertex=True)
        triangles = _maya_triangles(shape)
        before = _points(shape)
        before_volume = _signed_volume(shape, triangles)

        # 0番頂点を未選択の固定点として残し、残りを処理する。
        cmds.select(f"{shape}.vtx[1:{vertex_count - 1}]", replace=True)
        cmds.ywtaVolumeSmooth(iterations=5, strength=0.3, volumeCorrection=1.0, preserveRails=False)
        after = _points(shape)

        self.assertEqual(before[0], after[0])
        self.assertNotEqual(before, after)
        self.assertTrue(math.isclose(before_volume, _signed_volume(shape, triangles), rel_tol=1.0e-7, abs_tol=1.0e-8))

    def test_open_mesh_falls_back_without_volume_error(self):
        mesh, _ = cmds.polyPlane(name="openPlane", subdivisionsX=2, subdivisionsY=2)
        shape = cmds.listRelatives(mesh, shapes=True, noIntermediate=True)[0]
        before = _points(shape)
        cmds.select(mesh, replace=True)

        cmds.ywtaVolumeSmooth()
        after = _points(shape)
        self.assertEqual(len(before), len(after))
        self.assertTrue(all(all(math.isfinite(value) for value in point) for point in after))

    def test_soft_selection_becomes_continuous_vertex_weights(self):
        """Maya Soft Selectionのfalloffを二値化せずRustウェイトへ渡す。"""
        mesh, _ = cmds.polyPlane(name="softSelectionPlane", subdivisionsX=6, subdivisionsY=6)
        shape = cmds.listRelatives(mesh, shapes=True, noIntermediate=True)[0]
        previous_enabled = cmds.softSelect(query=True, softSelectEnabled=True)
        previous_distance = cmds.softSelect(query=True, softSelectDistance=True)
        try:
            cmds.softSelect(softSelectEnabled=True, softSelectDistance=1.5)
            cmds.select(f"{shape}.vtx[24]", replace=True)
            _path, _positions, _edges, _triangles, _closed, selected, weights, _rails = _shape_selection()
        finally:
            cmds.softSelect(softSelectEnabled=previous_enabled, softSelectDistance=previous_distance)

        influenced = [weight for weight in weights if 0.0 < weight < 1.0]
        self.assertEqual(weights[24], 1.0)
        self.assertTrue(influenced)
        self.assertGreater(len(selected), 1)

    def test_rail_chain_uses_tangent_and_fixes_endpoints(self):
        """railの内部頂点だけをRailLineにし、端点は固定する。"""
        positions = [0.0, 0.0, 0.0, 1.0, 0.1, 0.0, 2.0, 0.0, 0.0]
        weights = [1.0, 1.0, 1.0]
        modes = [0, 0, 0]

        directions = _apply_rail_constraints(positions, [0, 1, 1, 2], weights, modes)

        self.assertEqual(modes[0], 1)
        self.assertEqual(modes[1], 3)
        self.assertEqual(modes[2], 1)
        self.assertEqual(weights[0], 0.0)
        self.assertGreater(abs(directions[3]), 0.99)
        self.assertLess(abs(directions[4]), 1.0e-8)

    def test_selected_edge_is_collected_as_rail(self):
        """明示選択したedgeをhard/creaseと同じrail候補として扱う。"""
        mesh, _ = cmds.polyPlane(name="selectedRailPlane", subdivisionsX=3, subdivisionsY=3)
        shape = cmds.listRelatives(mesh, shapes=True, noIntermediate=True)[0]
        cmds.polySoftEdge(f"{shape}.e[*]", angle=180.0)
        cmds.select(f"{shape}.e[5]", replace=True)

        _path, _positions, _edges, _triangles, _closed, selected, weights, rails = _shape_selection()

        self.assertEqual(len(selected), len(weights))
        self.assertEqual(len(rails), 2)

    def test_hard_and_crease_edges_are_collected_as_rails(self):
        """Maya固有のhard edgeとcrease値をrail候補へ変換する。"""
        mesh, _ = cmds.polyPlane(name="hardCreaseRailPlane", subdivisionsX=3, subdivisionsY=3)
        shape = cmds.listRelatives(mesh, shapes=True, noIntermediate=True)[0]
        cmds.polySoftEdge(f"{shape}.e[*]", angle=180.0)
        selection = om2.MSelectionList()
        selection.add(shape)
        mesh_fn = om2.MFnMesh(selection.getDagPath(0))
        interior_edges = []
        for edge_id in range(mesh_fn.numEdges):
            first, second = mesh_fn.getEdgeVertices(edge_id)
            face_uses = sum(
                first in mesh_fn.getPolygonVertices(face) and second in mesh_fn.getPolygonVertices(face)
                for face in range(mesh_fn.numPolygons)
            )
            if face_uses == 2:
                interior_edges.append(edge_id)
        hard_edge, crease_edge = interior_edges[:2]
        cmds.polySoftEdge(f"{shape}.e[{hard_edge}]", angle=0.0)
        cmds.polyCrease(f"{shape}.e[{crease_edge}]", value=2.0)
        mesh_fn = om2.MFnMesh(selection.getDagPath(0))

        rails = _mesh_rail_edges(mesh_fn, set())
        rail_pairs = {tuple(sorted(pair)) for pair in zip(rails[::2], rails[1::2])}

        self.assertIn(tuple(sorted(mesh_fn.getEdgeVertices(hard_edge))), rail_pairs)
        self.assertIn(tuple(sorted(mesh_fn.getEdgeVertices(crease_edge))), rail_pairs)

    def test_solver_failure_does_not_modify_mesh(self):
        """Rust側の入力拒否時は元メッシュへ座標を書き戻さない。"""
        cube, _ = cmds.polyCube(name="invalidOptionsCube")
        shape = cmds.listRelatives(cube, shapes=True, noIntermediate=True)[0]
        before = _points(shape)
        cmds.select(cube, replace=True)

        with self.assertRaises(RuntimeError):
            cmds.ywtaVolumeSmooth(iterations=0)

        self.assertEqual(_points(shape), before)

    def test_plugin_unloads_cleanly(self):
        """コマンド登録を解除してプラグインを再ロード可能にする。"""
        cmds.unloadPlugin("ywtaVolumeSmoothing.py")
        self.assertFalse(cmds.pluginInfo("ywtaVolumeSmoothing.py", query=True, loaded=True))
        cmds.loadPlugin(str(_PLUGIN_PATH), quiet=True)

    def test_brush_geodesic_falloff_and_selection_mask(self):
        """純粋なfalloff計算が辺距離と選択範囲を守る。"""
        positions = [
            0.0,
            0.0,
            0.0,
            1.0,
            0.0,
            0.0,
            2.0,
            0.0,
            0.0,
            3.0,
            0.0,
            0.0,
        ]
        weights = _geodesic_brush_weights(
            positions,
            [0, 1, 1, 2, 2, 3],
            [[0, 1, 2]],
            0,
            (0.0, 0.0, 0.0),
            2.5,
            1.0,
            {0, 1, 2},
            {2},
        )
        self.assertGreater(weights[0], weights[1])
        self.assertEqual(weights[2], 0.0)
        self.assertEqual(weights[3], 0.0)

    def test_brush_context_registration_and_no_hit_cancel(self):
        """コンテキスト登録を確認し、hitなしではUndo状態を作らない。"""
        self.assertTrue(hasattr(cmds, "ywtaVolumeSmoothBrushContext"))
        mesh, _ = cmds.polyCube(name="brushContextCube")
        cmds.select(mesh, replace=True)
        context = VolumeSmoothingBrushContext()
        context.toolOnSetup(None)
        self.assertIsNone(context.apply_stroke_for_test([], face_index=0))

    def test_activate_brush_creates_named_context_and_selects_it(self):
        """GUIで使うhelperが名前付きcontextを生成して切り替える。"""
        with (
            mock.patch.object(cmds, "contextInfo", return_value=False),
            mock.patch.object(cmds, "ywtaVolumeSmoothBrushContext") as create_context,
            mock.patch.object(cmds, "setToolTo") as set_tool,
        ):
            context_name = activate_volume_smooth_brush()

        self.assertEqual(context_name, "ywtaVolumeSmoothBrushContext1")
        create_context.assert_called_once_with(context_name)
        set_tool.assert_called_once_with(context_name)

    def test_brush_session_reuse_and_single_stroke_transaction(self):
        """複数dabが1 sessionを再利用し、テストフックで1トランザクションになる。"""
        mesh, _ = cmds.polyCube(name="brushCube")
        shape = cmds.listRelatives(mesh, shapes=True, noIntermediate=True)[0]
        cmds.xform(f"{shape}.vtx[0]", objectSpace=True, translation=(-0.8, -0.5, 0.7))
        cmds.select(mesh, replace=True)
        context = VolumeSmoothingBrushContext()
        context.radius = 2.0
        context.toolOnSetup(None)
        self.assertIsNotNone(context._cache)
        session = context._cache.session
        triangles = _maya_triangles(shape)
        before = _points(shape)
        before_volume = _signed_volume(shape, triangles)

        transaction = context.apply_stroke_for_test(
            [(0.5, 0.5, 0.5), (0.45, 0.45, 0.45)],
            face_index=0,
        )
        after = _points(shape)
        self.assertIsNotNone(transaction)
        self.assertIs(context._cache.session, session)
        self.assertNotEqual(before, after)
        self.assertTrue(math.isclose(before_volume, _signed_volume(shape, triangles), rel_tol=1.0e-7, abs_tol=1.0e-8))

        # 既に確定したstrokeを残したまま、次のstrokeをキャンセルする。
        committed = _points(shape)
        self.assertTrue(context._begin_stroke())
        context._apply_hit(((0.4, 0.4, 0.4), 0))
        context.abortAction()
        self.assertEqual(_points(shape), committed)
        cmds.undo()
        self.assertEqual(_points(shape), before)
        cmds.redo()
        self.assertEqual(_points(shape), committed)


if __name__ == "__main__":
    unittest.main()
