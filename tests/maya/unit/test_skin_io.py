"""Skin IO の Maya 単体テスト。"""

import copy

import maya.cmds as cmds

from ywta.deform import skin_io
from ywta.test import TestCase


class SkinIoTests(TestCase):
    """同一トポロジーの保存・復元 contract を検証する。"""

    def setUp(self):
        self.mesh = cmds.polyPlane(name="cloth", subdivisionsX=1, subdivisionsY=1)[0]
        cmds.select(clear=True)
        self.joint_a = cmds.joint(name="root_jnt", position=(-1.0, 0.0, 0.0))
        cmds.select(clear=True)
        self.joint_b = cmds.joint(name="tip_jnt", position=(1.0, 0.0, 0.0))
        self.cluster = cmds.skinCluster(self.joint_a, self.joint_b, self.mesh, toSelectedBones=True, normalizeWeights=1)[0]
        vertices = cmds.ls(self.mesh + ".vtx[*]", flatten=True)
        for index, vertex in enumerate(vertices):
            weight = index / float(len(vertices) - 1)
            cmds.skinPercent(
                self.cluster,
                vertex,
                transformValue=((self.joint_a, 1.0 - weight), (self.joint_b, weight)),
            )

    def test_capture_and_apply_restore_weights(self):
        data = skin_io.capture(self.mesh)
        vertices = cmds.ls(self.mesh + ".vtx[*]", flatten=True)
        for vertex in vertices:
            cmds.skinPercent(
                self.cluster,
                vertex,
                transformValue=((self.joint_a, 1.0), (self.joint_b, 0.0)),
            )

        skin_io.apply(self.mesh, data)

        restored = skin_io.capture(self.mesh)
        for expected_row, actual_row in zip(data["weights"], restored["weights"]):
            self.assertEqual([entry[0] for entry in expected_row], [entry[0] for entry in actual_row])
            for expected, actual in zip(expected_row, actual_row):
                self.assertAlmostEqual(expected[1], actual[1], places=6)

    def test_save_and_read_round_trip(self):
        path = self.get_temp_filename("weights.json")

        skin_io.save(self.mesh, path)
        data = skin_io.read(path)

        self.assertEqual(skin_io.FORMAT, data["format"])
        self.assertEqual(4, data["mesh"]["topology"]["vertex_count"])
        self.assertEqual(2, len(data["influences"]))

    def test_apply_creates_skin_cluster_on_unskinned_mesh(self):
        data = skin_io.capture(self.mesh)
        target = cmds.duplicate(self.mesh, name="unskinned_target")[0]
        cmds.delete(target, constructionHistory=True)

        cluster = skin_io.apply(target, data)

        self.assertTrue(cmds.objExists(cluster))
        restored = skin_io.capture(target)
        self.assertEqual(data["weights"], restored["weights"])

    def test_apply_zeros_existing_extra_influence(self):
        data = skin_io.capture(self.mesh)
        cmds.select(clear=True)
        extra = cmds.joint(name="extra_jnt", position=(0.0, 1.0, 0.0))
        cmds.skinCluster(self.cluster, edit=True, addInfluence=extra, weight=1.0)

        skin_io.apply(self.mesh, data)

        vertices = cmds.ls(self.mesh + ".vtx[*]", flatten=True)
        extra_weights = [cmds.skinPercent(self.cluster, vertex, query=True, transform=extra) for vertex in vertices]
        self.assertTrue(all(abs(value) < 1.0e-8 for value in extra_weights))

    def test_same_vertex_count_with_changed_connectivity_is_rejected(self):
        data = skin_io.capture(self.mesh)
        data["mesh"]["topology"]["sha256"] = "0" * 64

        with self.assertRaises(ValueError):
            skin_io.apply(self.mesh, data)

    def test_invalid_weight_is_rejected_before_scene_edit(self):
        data = copy.deepcopy(skin_io.capture(self.mesh))
        data["weights"][0][0][1] = -1.0
        before = cmds.skinPercent(self.cluster, self.mesh + ".vtx[0]", query=True, value=True)

        with self.assertRaises(ValueError):
            skin_io.apply(self.mesh, data)

        after = cmds.skinPercent(self.cluster, self.mesh + ".vtx[0]", query=True, value=True)
        self.assertEqual(before, after)

    def test_missing_influence_is_rejected(self):
        data = skin_io.capture(self.mesh)
        cmds.delete(self.joint_b)

        with self.assertRaises(ValueError):
            skin_io.apply(self.mesh, data)
