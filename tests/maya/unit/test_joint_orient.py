"""静的Joint OrientationのMaya単体テスト。"""

import math
from unittest import mock

import maya.cmds as cmds

from ywta.rig import joint_edit_tools, joint_orient
from ywta.test import TestCase


class JointOrientTests(TestCase):
    """事前検証、world保持、Undoを検証する。"""

    def _chain(self, prefix=""):
        cmds.select(clear=True)
        parent = cmds.joint(name=prefix + "parent_jnt", position=(0.0, 0.0, 0.0))
        child = cmds.joint(name=prefix + "child_jnt", position=(3.0, 1.0, 0.0))
        grandchild = cmds.joint(name=prefix + "tip_jnt", position=(5.0, 2.0, 1.0))
        return parent, child, grandchild

    @staticmethod
    def _matrix(node):
        return cmds.xform(node, query=True, worldSpace=True, matrix=True)

    def assert_matrix_almost_equal(self, expected, actual):
        for left, right in zip(expected, actual):
            self.assertAlmostEqual(left, right, places=7)

    def test_orient_preserves_descendant_world_matrices_and_undoes(self):
        parent, child, grandchild = self._chain()
        before_child = self._matrix(child)
        before_grandchild = self._matrix(grandchild)
        before_orient = cmds.getAttr(parent + ".jointOrient")[0]
        cmds.select(parent, replace=True)

        result = joint_orient.orient_to_children([parent])

        self.assertEqual(["|parent_jnt"], result)
        self.assertEqual((0.0, 0.0, 0.0), cmds.getAttr(parent + ".rotate")[0])
        self.assertGreater(abs(cmds.getAttr(parent + ".jointOrientZ")), 1.0)
        self.assert_matrix_almost_equal(before_child, self._matrix(child))
        self.assert_matrix_almost_equal(before_grandchild, self._matrix(grandchild))
        self.assertEqual([parent], cmds.ls(selection=True))

        cmds.undo()
        self.assertEqual(before_orient, cmds.getAttr(parent + ".jointOrient")[0])
        self.assert_matrix_almost_equal(before_child, self._matrix(child))
        cmds.redo()
        self.assertGreater(abs(cmds.getAttr(parent + ".jointOrientZ")), 1.0)

    def test_hierarchy_entry_orients_non_leaf_joints(self):
        parent, child, _grandchild = self._chain()
        cmds.select(parent, replace=True)

        result = joint_orient.orient_selected(include_descendants=True)

        self.assertEqual({"parent_jnt", "child_jnt"}, {node.rsplit("|", 1)[-1] for node in result})
        self.assertGreater(abs(cmds.getAttr(parent + ".jointOrientZ")), 1.0)
        self.assertGreater(
            sum(abs(value) for value in cmds.getAttr(child + ".jointOrient")[0]),
            1.0,
        )

    def test_negative_x_chain_aims_local_x_and_preserves_descendants(self):
        """ミラー側chainでもlocal +Xを子方向へ向けworld姿勢を保つ。"""
        cmds.select(clear=True)
        parent = cmds.joint(name="R_parent_jnt", position=(0.0, 0.0, 0.0))
        child = cmds.joint(name="R_child_jnt", position=(-3.0, 1.0, 0.0))
        grandchild = cmds.joint(name="R_tip_jnt", position=(-5.0, 2.0, 1.0))
        before_child = self._matrix(child)
        before_grandchild = self._matrix(grandchild)

        joint_orient.orient_to_children([parent])

        matrix = self._matrix(parent)
        aim = [before_child[12] - matrix[12], before_child[13] - matrix[13], before_child[14] - matrix[14]]
        aim_length = math.sqrt(sum(value * value for value in aim))
        local_x = matrix[:3]
        alignment = sum(axis * direction / aim_length for axis, direction in zip(local_x, aim))
        self.assertAlmostEqual(1.0, alignment, places=7)
        self.assert_matrix_almost_equal(before_child, self._matrix(child))
        self.assert_matrix_almost_equal(before_grandchild, self._matrix(grandchild))

        cmds.undo()
        self.assert_matrix_almost_equal(before_child, self._matrix(child))
        self.assert_matrix_almost_equal(before_grandchild, self._matrix(grandchild))

    def test_invalid_later_joint_preflights_before_first_edit(self):
        parent, _child, _grandchild = self._chain("a_")
        cmds.select(clear=True)
        leaf = cmds.joint(name="leaf_jnt", position=(8.0, 0.0, 0.0))
        before = cmds.getAttr(parent + ".jointOrient")[0]

        with self.assertRaises(ValueError):
            joint_orient.orient_to_children([parent, leaf])

        self.assertEqual(before, cmds.getAttr(parent + ".jointOrient")[0])

    def test_skinned_joint_rejects_before_edit(self):
        parent, child, _grandchild = self._chain()
        mesh = cmds.polyCube(name="body")[0]
        cmds.skinCluster(parent, child, mesh, toSelectedBones=True)
        before = cmds.getAttr(parent + ".jointOrient")[0]

        with self.assertRaises(ValueError):
            joint_orient.orient_to_children([parent])

        self.assertEqual(before, cmds.getAttr(parent + ".jointOrient")[0])

    def test_second_orient_failure_rolls_back_first(self):
        parent, child, _grandchild = self._chain()
        before_parent = cmds.getAttr(parent + ".jointOrient")[0]
        before_child = cmds.getAttr(child + ".jointOrient")[0]
        original_joint = joint_orient.cmds.joint
        calls = 0

        def fail_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("expected failure")
            return original_joint(*args, **kwargs)

        with mock.patch.object(joint_orient.cmds, "joint", side_effect=fail_second):
            with self.assertRaises(RuntimeError):
                joint_orient.orient_to_children([parent, child])

        self.assertEqual(before_parent, cmds.getAttr(parent + ".jointOrient")[0])
        self.assertEqual(before_child, cmds.getAttr(child + ".jointOrient")[0])

    def test_nonzero_rotate_and_zero_length_reject_before_edit(self):
        parent, _child, _grandchild = self._chain("rotated_")
        cmds.setAttr(parent + ".rotateX", 5.0)
        with self.assertRaises(ValueError):
            joint_orient.orient_to_children([parent])

        cmds.select(clear=True)
        zero_parent = cmds.joint(name="zero_parent", position=(0.0, 0.0, 0.0))
        cmds.joint(name="zero_child", position=(0.0, 0.0, 0.0))
        with self.assertRaises(ValueError):
            joint_orient.orient_to_children([zero_parent])

    def test_joint_edit_tools_routes_align_through_safe_entry(self):
        """旧windowのAlign with Childも階層orientを使う。"""
        window = joint_edit_tools.JointEditToolsWindow.__new__(joint_edit_tools.JointEditToolsWindow)

        with (
            mock.patch.object(window, "_get_recursive_setting", return_value=False),
            mock.patch.object(joint_edit_tools.joint_orient, "orient_selected") as orient_selected,
        ):
            window._align_with_child()

        orient_selected.assert_called_once_with(include_descendants=False)

    def test_legacy_align_function_routes_through_safe_core(self):
        """従来公開APIに一時constraint実装を残さない。"""
        with mock.patch.object(
            joint_edit_tools.joint_orient,
            "orient_to_children",
            return_value=["|parent_jnt"],
        ) as orient:
            result = joint_edit_tools.align_with_child(["parent_jnt"])

        self.assertEqual(["|parent_jnt"], result)
        orient.assert_called_once_with(["parent_jnt"])
