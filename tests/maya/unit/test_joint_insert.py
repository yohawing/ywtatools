"""隣接joint間への安全な挿入テスト。"""

from unittest import mock

import maya.cmds as cmds

from ywta.rig import joint_insert
from ywta.test import TestCase


class JointInsertTests(TestCase):
    """均等位置、階層、world姿勢、拒否条件、Undoを検証する。"""

    @staticmethod
    def _chain():
        cmds.select(clear=True)
        parent = cmds.joint(name="parent_jnt", position=(0.0, 0.0, 0.0))
        child = cmds.joint(name="child_jnt", position=(9.0, 3.0, 0.0))
        cmds.setAttr(parent + ".jointOrientZ", 20.0)
        return parent, child

    def test_insert_evenly_preserves_child_world_matrix_and_undoes(self):
        parent, child = self._chain()
        child_matrix = cmds.xform(child, query=True, worldSpace=True, matrix=True)
        start = cmds.xform(parent, query=True, worldSpace=True, translation=True)
        end = cmds.xform(child, query=True, worldSpace=True, translation=True)
        expected_positions = [
            [start[axis] + (end[axis] - start[axis]) * fraction for axis in range(3)] for fraction in (1.0 / 3.0, 2.0 / 3.0)
        ]

        created = joint_insert.insert_joints(parent, child, count=2, name_pattern="twist_##_jnt")

        self.assertEqual(["|parent_jnt|twist_01_jnt", "|parent_jnt|twist_01_jnt|twist_02_jnt"], created)
        for joint, expected_position in zip(created, expected_positions):
            actual_position = cmds.xform(joint, query=True, worldSpace=True, translation=True)
            for expected, actual in zip(expected_position, actual_position):
                self.assertAlmostEqual(expected, actual)
        actual_matrix = cmds.xform(child, query=True, worldSpace=True, matrix=True)
        for expected, actual in zip(child_matrix, actual_matrix):
            self.assertAlmostEqual(expected, actual)
        self.assertEqual(created, cmds.ls(selection=True, long=True))

        cmds.undo()
        self.assertFalse(cmds.objExists("twist_01_jnt"))
        self.assertEqual(["child_jnt"], cmds.listRelatives(parent, children=True, type="joint"))
        cmds.redo()
        self.assertTrue(cmds.objExists("twist_02_jnt"))

    def test_branching_parent_rejects_before_edit(self):
        parent, child = self._chain()
        cmds.select(parent, replace=True)
        sibling = cmds.joint(name="sibling_jnt", position=(0.0, 4.0, 0.0))

        with self.assertRaises(ValueError):
            joint_insert.insert_joints(parent, child)

        self.assertTrue(cmds.objExists(sibling))
        self.assertFalse(cmds.objExists("insert_01_jnt"))

    def test_skinned_joint_rejects_before_edit(self):
        parent, child = self._chain()
        mesh = cmds.polyPlane(name="skin_mesh")[0]
        cmds.skinCluster(parent, child, mesh, toSelectedBones=True)

        with self.assertRaises(ValueError):
            joint_insert.insert_joints(parent, child)

        self.assertFalse(cmds.objExists("insert_01_jnt"))

    def test_invalid_count_and_name_collision_reject_before_edit(self):
        parent, child = self._chain()
        cmds.createNode("transform", name="insert_01_jnt")

        with self.assertRaises(ValueError):
            joint_insert.insert_joints(parent, child, count=0)
        with self.assertRaises(ValueError):
            joint_insert.insert_joints(parent, child)

        self.assertEqual(["child_jnt"], cmds.listRelatives(parent, children=True, type="joint"))

    def test_namespace_is_inherited_from_parent(self):
        cmds.namespace(add="character")
        cmds.select(clear=True)
        parent = cmds.joint(name="character:parent_jnt", position=(0.0, 0.0, 0.0))
        child = cmds.joint(name="character:child_jnt", position=(3.0, 0.0, 0.0))

        created = joint_insert.insert_joints(parent, child)

        self.assertEqual(["|character:parent_jnt|character:insert_01_jnt"], created)

    def test_second_insert_failure_rolls_back_first_insert(self):
        parent, child = self._chain()
        original_insert = joint_insert.cmds.insertJoint
        calls = 0

        def fail_second(node):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("expected failure")
            return original_insert(node)

        with mock.patch.object(joint_insert.cmds, "insertJoint", side_effect=fail_second):
            with self.assertRaises(RuntimeError):
                joint_insert.insert_joints(parent, child, count=2)

        self.assertFalse(cmds.objExists("insert_01_jnt"))
        self.assertEqual(["child_jnt"], cmds.listRelatives(parent, children=True, type="joint"))
