"""Undoable bulk skin weight command境界のMaya単体テスト。"""

import maya.cmds as cmds

from ywta.deform import skin_weight_command
from ywta.test import TestCase


class SkinWeightCommandTests(TestCase):
    """配列shapeと値をMFnSkinCluster到達前に拒否する。"""

    def setUp(self):
        self.mesh = cmds.polyPlane(name="cloth")[0]
        self.shape = cmds.listRelatives(self.mesh, shapes=True, fullPath=True)[0]
        cmds.select(clear=True)
        self.joint = cmds.joint(name="root_jnt")
        cmds.select(clear=True)
        self.tip = cmds.joint(name="tip_jnt", position=(1.0, 0.0, 0.0))
        self.cluster = cmds.skinCluster(
            self.joint,
            self.tip,
            self.mesh,
            toSelectedBones=True,
        )[0]
        cmds.skinPercent(
            self.cluster,
            self.mesh + ".vtx[0]",
            transformValue=((self.joint, 0.5), (self.tip, 0.5)),
        )

    def _weights(self):
        return cmds.skinPercent(
            self.cluster,
            self.mesh + ".vtx[0]",
            query=True,
            value=True,
        )

    def test_wrong_weight_count_fails_before_edit(self):
        before = self._weights()

        with self.assertRaises(ValueError):
            skin_weight_command.execute(
                self.cluster,
                self.shape,
                [0, 1],
                [0, 1],
                [1.0],
            )

        self.assertEqual(before, self._weights())

    def test_duplicate_component_and_nonfinite_weight_are_rejected(self):
        with self.assertRaises(ValueError):
            skin_weight_command.execute(
                self.cluster,
                self.shape,
                [0, 0],
                [0, 1],
                [1.0, 0.0, 1.0, 0.0],
            )
        with self.assertRaises(ValueError):
            skin_weight_command.execute(
                self.cluster,
                self.shape,
                [0],
                [0],
                [float("nan")],
            )

    def test_direct_command_write_is_undoable(self):
        skin_weight_command.execute(
            self.cluster,
            self.shape,
            [0],
            [0, 1],
            [1.0, 0.0],
        )

        self.assertEqual([1.0, 0.0], self._weights())
        cmds.undo()
        self.assertEqual([0.5, 0.5], self._weights())

    def test_subset_influence_write_restores_full_old_weights(self):
        """1 influenceだけのAPI writeでもUndoで全weightを正確に戻す。"""
        cmds.skinPercent(
            self.cluster,
            self.mesh + ".vtx[0]",
            transformValue=((self.joint, 0.25), (self.tip, 0.75)),
        )
        before = self._weights()

        skin_weight_command.execute(
            self.cluster,
            self.shape,
            [0],
            [0],
            [0.5],
            normalize=False,
        )
        self.assertNotEqual(before, self._weights())

        cmds.undo()
        for expected, actual in zip(before, self._weights()):
            self.assertAlmostEqual(expected, actual)

    def test_wrong_cluster_shape_and_out_of_range_indices_are_rejected(self):
        """MFnSkinClusterへ不整合node/indexを渡さない。"""
        other = cmds.polyPlane(name="other")[0]
        other_shape = cmds.listRelatives(other, shapes=True, fullPath=True)[0]
        before = self._weights()

        with self.assertRaises(ValueError):
            skin_weight_command.execute(self.cluster, other_shape, [0], [0], [1.0])
        with self.assertRaises(ValueError):
            skin_weight_command.execute(self.cluster, self.shape, [999], [0], [1.0])
        with self.assertRaises(ValueError):
            skin_weight_command.execute(self.cluster, self.shape, [0], [999], [1.0])

        self.assertEqual(before, self._weights())
        self.assertFalse(skin_weight_command._OPERATIONS)
