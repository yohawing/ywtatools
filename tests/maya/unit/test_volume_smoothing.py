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
    _geodesic_brush_weights,
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


def _signed_volume(shape):
    """面の頂点順をファン分割して符号付き体積を計算する。"""
    selection = om2.MSelectionList()
    selection.add(shape)
    dag_path = selection.getDagPath(0)
    mesh_fn = om2.MFnMesh(dag_path)
    points = mesh_fn.getPoints(om2.MSpace.kObject)
    face_counts, face_indices = mesh_fn.getVertices()
    volume = 0.0
    offset = 0
    for raw_count in face_counts:
        count = int(raw_count)
        vertices = [int(index) for index in face_indices[offset : offset + count]]
        offset += count
        for index in range(1, count - 1):
            a, b, c = (points[vertices[0]], points[vertices[index]], points[vertices[index + 1]])
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
        before = _points(shape)
        before_volume = _signed_volume(shape)

        cmds.select(cube, replace=True)
        cmds.ywtaVolumeSmooth()
        after = _points(shape)
        after_volume = _signed_volume(shape)

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

    def test_open_mesh_falls_back_without_volume_error(self):
        mesh, _ = cmds.polyPlane(name="openPlane", subdivisionsX=2, subdivisionsY=2)
        shape = cmds.listRelatives(mesh, shapes=True, noIntermediate=True)[0]
        before = _points(shape)
        cmds.select(mesh, replace=True)

        cmds.ywtaVolumeSmooth()
        after = _points(shape)
        self.assertEqual(len(before), len(after))
        self.assertTrue(all(all(math.isfinite(value) for value in point) for point in after))

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
        before = _points(shape)
        before_volume = _signed_volume(shape)

        transaction = context.apply_stroke_for_test(
            [(0.5, 0.5, 0.5), (0.45, 0.45, 0.45)],
            face_index=0,
        )
        after = _points(shape)
        self.assertIsNotNone(transaction)
        self.assertIs(context._cache.session, session)
        self.assertNotEqual(before, after)
        self.assertTrue(math.isclose(before_volume, _signed_volume(shape), rel_tol=1.0e-7, abs_tol=1.0e-8))

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
