"""Skin Influence Cleanup の Maya 単体テスト。"""

import maya.cmds as cmds

from ywta.deform import influence_cleanup
from ywta.test import TestCase


class InfluenceCleanupTests(TestCase):
    """全geometry走査、lock保護、Undoを検証する。"""

    def setUp(self):
        self.mesh = cmds.polyPlane(name="cloth")[0]
        cmds.select(clear=True)
        self.root = cmds.joint(name="root_jnt", position=(-1.0, 0.0, 0.0))
        cmds.select(clear=True)
        self.tip = cmds.joint(name="tip_jnt", position=(1.0, 0.0, 0.0))
        cmds.select(clear=True)
        self.unused = cmds.joint(name="unused_jnt", position=(0.0, 1.0, 0.0))
        self.cluster = cmds.skinCluster(
            self.root,
            self.tip,
            self.unused,
            self.mesh,
            toSelectedBones=True,
            normalizeWeights=1,
        )[0]
        vertices = cmds.ls(self.mesh + ".vtx[*]", flatten=True)
        for index, vertex in enumerate(vertices):
            root_weight = 1.0 if index < 2 else 0.0
            cmds.skinPercent(
                self.cluster,
                vertex,
                transformValue=(
                    (self.root, root_weight),
                    (self.tip, 1.0 - root_weight),
                    (self.unused, 0.0),
                ),
            )

    @staticmethod
    def _short_names(records):
        """解析結果の influence を比較用の短い名前へ変換する。"""
        return [record["influence"].rsplit("|", 1)[-1] for record in records]

    def test_find_unused_influence(self):
        result = influence_cleanup.find_unused_influences([self.mesh])

        records = result[self.cluster]
        self.assertEqual(["unused_jnt"], self._short_names(records))
        self.assertEqual(0.0, records[0]["maximum_weight"])

    def test_remove_unused_is_single_undoable_action(self):
        before = cmds.skinCluster(self.cluster, query=True, influence=True)

        result = influence_cleanup.remove_unused_influences([self.mesh])

        self.assertEqual(1, len(result["removed"]))
        self.assertNotIn(self.unused, cmds.skinCluster(self.cluster, query=True, influence=True))
        cmds.undo()
        self.assertEqual(before, cmds.skinCluster(self.cluster, query=True, influence=True))
        cmds.redo()
        self.assertNotIn(self.unused, cmds.skinCluster(self.cluster, query=True, influence=True))

    def test_locked_unused_influence_is_protected(self):
        cmds.setAttr(self.unused + ".lockInfluenceWeights", True)

        result = influence_cleanup.remove_unused_influences([self.mesh])

        self.assertFalse(result["removed"])
        self.assertEqual("locked", result["protected"][0]["reason"])
        self.assertIn(self.unused, cmds.skinCluster(self.cluster, query=True, influence=True))

    def test_threshold_controls_small_weight_candidate(self):
        vertex = cmds.ls(self.mesh + ".vtx[*]", flatten=True)[0]
        cmds.skinPercent(
            self.cluster,
            vertex,
            transformValue=((self.root, 0.999), (self.unused, 0.001)),
        )

        strict = influence_cleanup.analyze_cluster(self.cluster, threshold=0.0001)
        loose = influence_cleanup.analyze_cluster(self.cluster, threshold=0.01)

        self.assertNotIn(self.unused, self._short_names(strict))
        self.assertIn(self.unused, self._short_names(loose))

    def test_invalid_threshold_fails_before_edit(self):
        before = cmds.skinCluster(self.cluster, query=True, influence=True)

        with self.assertRaises(ValueError):
            influence_cleanup.remove_unused_influences([self.mesh], threshold=-1.0)

        self.assertEqual(before, cmds.skinCluster(self.cluster, query=True, influence=True))
