"""Skinned mesh結合のMaya単体テスト。"""

import os
from unittest import mock

import maya.api.OpenMaya as om
import maya.api.OpenMayaAnim as oma
import maya.cmds as cmds

from ywta.deform import combine_skinned
from ywta.deform import skin_io
from ywta.test import TestCase


class CombineSkinnedTests(TestCase):
    """元mesh非破壊、正確なweight mapping、Undoを検証する。"""

    def _source(self, name, offset, influences, weights):
        """異なる位置とウェイトを持つplaneを作成する。"""
        mesh = cmds.polyPlane(name=name, width=1.0, height=1.0, subdivisionsX=1, subdivisionsY=1)[0]
        cmds.move(offset, 0.0, 0.0, mesh)
        cluster = cmds.skinCluster(influences, mesh, toSelectedBones=True, normalizeWeights=1)[0]
        for vertex_index, row in enumerate(weights):
            cmds.skinPercent(
                cluster,
                "{}.vtx[{}]".format(mesh, vertex_index),
                transformValue=list(zip(influences, row)),
            )
        return mesh

    @staticmethod
    def _dense_weights(mesh):
        """meshのweightとinfluence leaf名を返す。"""
        shape = skin_io._mesh_shape(mesh)
        cluster = skin_io._skin_cluster(shape)
        fn_skin = oma.MFnSkinCluster(skin_io._depend_node(cluster))
        influences = [path.fullPathName().rsplit("|", 1)[-1] for path in fn_skin.influenceObjects()]
        count = om.MFnMesh(skin_io._dag_path(shape)).numVertices
        weights, influence_count = fn_skin.getWeights(skin_io._dag_path(shape), skin_io._vertex_component(count))
        rows = [list(weights[index * influence_count : (index + 1) * influence_count]) for index in range(count)]
        return influences, rows

    def setUp(self):
        cmds.select(clear=True)
        self.left_joint = cmds.joint(name="left_jnt", position=(-1.0, 0.0, 0.0))
        cmds.select(clear=True)
        self.right_joint = cmds.joint(name="right_jnt", position=(1.0, 0.0, 0.0))
        self.left = self._source(
            "left_mesh",
            -2.0,
            [self.left_joint, self.right_joint],
            [(1.0, 0.0), (0.75, 0.25), (0.5, 0.5), (0.25, 0.75)],
        )
        self.right = self._source(
            "right_mesh",
            2.0,
            [self.right_joint, self.left_joint],
            [(1.0, 0.0), (0.6, 0.4), (0.2, 0.8), (0.0, 1.0)],
        )

    def test_combines_exact_weights_without_changing_sources(self):
        left_uuid = cmds.ls(self.left, uuid=True)[0]
        right_uuid = cmds.ls(self.right, uuid=True)[0]

        result = combine_skinned.combine([self.left, self.right], name="body_mesh")

        self.assertEqual(8, result["vertex_count"])
        self.assertEqual(left_uuid, cmds.ls(self.left, uuid=True)[0])
        self.assertEqual(right_uuid, cmds.ls(self.right, uuid=True)[0])
        influences, rows = self._dense_weights(result["mesh"])
        expected = []
        for source in (self.left, self.right):
            source_influences, source_rows = self._dense_weights(source)
            for row in source_rows:
                by_name = dict(zip(source_influences, row))
                expected.append([by_name.get(influence, 0.0) for influence in influences])
        for actual_row, expected_row in zip(rows, expected):
            for actual, expected_value in zip(actual_row, expected_row):
                self.assertAlmostEqual(expected_value, actual)

    def test_connectivity_mismatch_rolls_back_without_changing_sources(self):
        """座標が一致してもface connectivity不一致なら結合を残さない。"""
        left_uuid = cmds.ls(self.left, uuid=True)[0]
        right_uuid = cmds.ls(self.right, uuid=True)[0]
        cmds.select(self.left, self.right, replace=True)
        original_topology = combine_skinned._topology
        calls = 0

        def mismatch_output(shape):
            nonlocal calls
            calls += 1
            return original_topology(shape) if calls <= 2 else ([], [])

        with mock.patch.object(combine_skinned, "_topology", side_effect=mismatch_output):
            with self.assertRaises(RuntimeError):
                combine_skinned.combine([self.left, self.right], name="body_mesh")

        self.assertFalse(cmds.objExists("body_mesh"))
        self.assertEqual(left_uuid, cmds.ls(self.left, uuid=True)[0])
        self.assertEqual(right_uuid, cmds.ls(self.right, uuid=True)[0])
        self.assertEqual({self.left, self.right}, set(cmds.ls(selection=True)))

    def test_combine_is_single_undoable_action(self):
        cmds.select(self.left, self.right, replace=True)
        result = combine_skinned.combine([self.left, self.right], name="body_mesh")
        combined_uuid = cmds.ls(result["mesh"], uuid=True)[0]

        self.assertEqual(["body_mesh"], cmds.ls(selection=True))

        cmds.undo()

        self.assertFalse(cmds.ls(combined_uuid, uuid=True))
        self.assertTrue(cmds.objExists(self.left))
        self.assertTrue(cmds.objExists(self.right))
        self.assertEqual({self.left, self.right}, set(cmds.ls(selection=True)))

    def test_locked_source_influence_rejects_before_combine(self):
        """新規skinCluster作成でsource joint lockを解除しない。"""
        cmds.setAttr(self.left_joint + ".lockInfluenceWeights", True)

        with self.assertRaises(ValueError):
            combine_skinned.combine([self.left, self.right], name="body_mesh")

        self.assertFalse(cmds.objExists("body_mesh"))
        self.assertTrue(cmds.objExists(self.left))
        self.assertTrue(cmds.objExists(self.right))
        self.assertTrue(cmds.getAttr(self.left_joint + ".lockInfluenceWeights"))

    def test_skin_io_saves_multiple_meshes_without_scene_changes(self):
        """複数meshを1 JSONへ保存し、一時結合meshとscene差分を残さない。"""
        left_uuid = cmds.ls(self.left, uuid=True)[0]
        right_uuid = cmds.ls(self.right, uuid=True)[0]
        path = self.get_temp_filename("combined_skin.json")
        cmds.select(self.left, self.right, replace=True)
        cmds.setAttr(self.left_joint + ".radius", 2.0)

        result = skin_io.save_combined([self.left, self.right], path)

        self.assertEqual(os.path.abspath(path), result)
        data = skin_io.read(path)
        self.assertEqual(8, data["mesh"]["topology"]["vertex_count"])
        self.assertEqual(8, len(data["weights"]))
        self.assertEqual(left_uuid, cmds.ls(self.left, uuid=True)[0])
        self.assertEqual(right_uuid, cmds.ls(self.right, uuid=True)[0])
        self.assertEqual({self.left, self.right}, set(cmds.ls(selection=True)))
        cmds.undo()
        self.assertAlmostEqual(1.0, cmds.getAttr(self.left_joint + ".radius"))
        cmds.redo()
        self.assertAlmostEqual(2.0, cmds.getAttr(self.left_joint + ".radius"))

    def test_virtual_skin_combine_matches_exact_mesh_combine(self):
        """virtual geometry fingerprintが実polyUniteの検証済み頂点順と一致する。"""
        path = self.get_temp_filename("virtual_skin.json")
        skin_io.save_combined([self.left, self.right], path)
        expected = skin_io.read(path)

        result = combine_skinned.combine([self.left, self.right], name="actual_combined")
        actual = skin_io.capture(result["mesh"])

        self.assertEqual(expected["mesh"]["topology"], actual["mesh"]["topology"])
        self.assertEqual(expected["mesh"]["geometry"], actual["mesh"]["geometry"])
        expected_paths = [item["path"] for item in expected["influences"]]
        actual_paths = [item["path"] for item in actual["influences"]]
        for expected_row, actual_row in zip(expected["weights"], actual["weights"]):
            expected_weights = {expected_paths[index]: value for index, value in expected_row}
            actual_weights = {actual_paths[index]: value for index, value in actual_row}
            self.assertEqual(set(expected_weights), set(actual_weights))
            for path, value in expected_weights.items():
                self.assertAlmostEqual(value, actual_weights[path], places=6)

    def test_multi_mesh_skin_capture_failure_leaves_scene_unchanged(self):
        """virtual capture失敗でもファイルとscene差分を残さない。"""
        path = self.get_temp_filename("failed_combined_skin.json")
        cmds.select(self.left, self.right, replace=True)
        original_capture = skin_io.capture
        call_count = [0]

        def fail_combined_capture(mesh):
            call_count[0] += 1
            if call_count[0] == 2:
                raise RuntimeError("forced capture failure")
            return original_capture(mesh)

        with mock.patch.object(skin_io, "capture", side_effect=fail_combined_capture):
            with self.assertRaises(RuntimeError):
                skin_io.save_combined([self.left, self.right], path)

        self.assertFalse(os.path.exists(path))
        self.assertEqual({self.left, self.right}, set(cmds.ls(selection=True)))

    def test_multi_mesh_skin_save_rejects_duplicate_source(self):
        """同じmeshの二重連結をファイル作成前に拒否する。"""
        path = self.get_temp_filename("duplicate_combined_skin.json")

        with self.assertRaises(ValueError):
            skin_io.save_combined([self.left, self.left], path)

        self.assertFalse(os.path.exists(path))

    def test_skin_io_menu_save_accepts_multiple_selected_meshes(self):
        """Save Skin Weights入口が複数選択をcombined保存へ振り分ける。"""
        path = self.get_temp_filename("selected_combined_skin.json")
        cmds.select(self.left, self.right, replace=True)

        with mock.patch.object(skin_io.cmds, "fileDialog2", return_value=[path]):
            result = skin_io.save_selected()

        self.assertEqual(os.path.abspath(path), result)
        self.assertEqual(8, skin_io.read(path)["mesh"]["topology"]["vertex_count"])
        self.assertEqual({self.left, self.right}, set(cmds.ls(selection=True)))

    def test_unskinned_source_fails_before_edit(self):
        plain = cmds.polyCube(name="plain_mesh")[0]

        with self.assertRaises(ValueError):
            combine_skinned.combine([self.left, plain])

        self.assertTrue(cmds.objExists(self.left))
        self.assertTrue(cmds.objExists(plain))
        self.assertFalse(cmds.objExists("combined_skinned_mesh"))

    def test_output_name_collision_fails_before_edit(self):
        occupied = cmds.createNode("transform", name="body_mesh")
        before = set(cmds.ls(long=True))

        with self.assertRaises(ValueError):
            combine_skinned.combine([self.left, self.right], name="body_mesh")

        self.assertEqual(before, set(cmds.ls(long=True)))
        self.assertTrue(cmds.objExists(occupied))

    def test_invalid_output_name_and_single_string_fail_before_undo(self):
        """不正出力名と単一mesh文字列をscene編集前に拒否する。"""
        cmds.undoInfo(stateWithoutFlush=False)
        try:
            for invalid in ("bad name", "1mesh", "mesh#", "mesh-name", "missing:mesh"):
                with self.assertRaises(ValueError):
                    combine_skinned.combine([self.left, self.right], name=invalid)
            with self.assertRaises(ValueError):
                combine_skinned.combine(self.left)
        finally:
            cmds.undoInfo(stateWithoutFlush=True)

        self.assertFalse(cmds.objExists("bad_name"))

    def test_explicit_namespace_is_independent_of_current_namespace(self):
        cmds.namespace(add="character")
        cmds.namespace(add="working")
        cmds.namespace(set="working")

        result = combine_skinned.combine(
            [self.left, self.right],
            name="character:body_mesh",
        )
        cmds.namespace(set=":")

        self.assertEqual("character:body_mesh", result["mesh"].rsplit("|", 1)[-1])
        self.assertFalse(cmds.objExists(":working:character:body_mesh"))

    def test_unqualified_output_name_targets_root_namespace(self):
        cmds.namespace(add="working")
        cmds.namespace(set="working")

        result = combine_skinned.combine(
            [self.left, self.right],
            name="body_mesh",
        )
        cmds.namespace(set=":")

        self.assertEqual("body_mesh", result["mesh"].rsplit("|", 1)[-1])
        self.assertFalse(cmds.objExists(":working:body_mesh"))
