"""Duplicate Joint HierarchyのMaya単体テスト。"""

from unittest import mock

import maya.cmds as cmds

from ywta.rig import joint_duplicate
from ywta.test import TestCase


class JointDuplicateTests(TestCase):
    """名前検証、階層保持、rollbackを検証する。"""

    def _chain(self, namespace=""):
        if namespace and not cmds.namespace(exists=namespace):
            cmds.namespace(add=namespace)
        prefix = namespace + ":" if namespace else ""
        cmds.select(clear=True)
        root = cmds.joint(name=prefix + "L_arm_jnt", position=(2.0, 0.0, 0.0))
        child = cmds.joint(name=prefix + "L_elbow_jnt", position=(4.0, 1.0, 0.0))
        tip = cmds.joint(name=prefix + "L_wrist_jnt", position=(6.0, 1.0, 0.0))
        return root, child, tip

    @staticmethod
    def _matrix(node):
        return cmds.xform(node, query=True, worldSpace=True, matrix=True)

    def test_duplicate_preserves_hierarchy_names_matrices_and_undo(self):
        root, child, tip = self._chain()
        source_matrices = [self._matrix(node) for node in (root, child, tip)]

        created = joint_duplicate.duplicate_hierarchy(root, "L_", "R_")

        self.assertEqual(
            ["R_arm_jnt", "R_elbow_jnt", "R_wrist_jnt"],
            [node.rsplit("|", 1)[-1] for node in created],
        )
        self.assertEqual(created[0], cmds.listRelatives(created[1], parent=True, fullPath=True)[0])
        self.assertEqual(created[1], cmds.listRelatives(created[2], parent=True, fullPath=True)[0])
        for source_matrix, node in zip(source_matrices, created):
            for expected, actual in zip(source_matrix, self._matrix(node)):
                self.assertAlmostEqual(expected, actual, places=7)
        root_uuid = cmds.ls(created[0], uuid=True)[0]
        cmds.undo()
        self.assertFalse(cmds.ls(root_uuid, uuid=True))
        cmds.redo()
        self.assertTrue(cmds.ls(root_uuid, uuid=True))

    def test_namespace_is_preserved_independent_of_current_namespace(self):
        root, _child, _tip = self._chain("character")
        cmds.namespace(add="working")
        cmds.namespace(set="working")

        created = joint_duplicate.duplicate_hierarchy(root, "L_", "R_")
        cmds.namespace(set=":")

        self.assertEqual("character:R_arm_jnt", created[0].rsplit("|", 1)[-1])
        self.assertFalse(cmds.objExists(":working:character:R_arm_jnt"))

    def test_mid_chain_root_duplicates_as_sibling_under_same_parent(self):
        cmds.select(clear=True)
        skeleton_root = cmds.joint(name="skeleton_root", position=(0.0, 2.0, 0.0))
        source = cmds.joint(name="L_arm_jnt", position=(2.0, 3.0, 0.0))
        cmds.joint(name="L_elbow_jnt", position=(4.0, 3.0, 0.0))
        before = self._matrix(source)

        created = joint_duplicate.duplicate_hierarchy(source, "L_", "R_")

        self.assertEqual(
            cmds.ls(skeleton_root, long=True)[0],
            cmds.listRelatives(created[0], parent=True, fullPath=True)[0],
        )
        for expected, actual in zip(before, self._matrix(created[0])):
            self.assertAlmostEqual(expected, actual, places=7)

    def test_unmatched_name_and_existing_target_reject_before_edit(self):
        root, _child, _tip = self._chain()
        before = cmds.ls(type="joint", long=True)

        with self.assertRaises(ValueError):
            joint_duplicate.duplicate_hierarchy(root, "missing", "R_")
        cmds.select(clear=True)
        cmds.joint(name="R_arm_jnt")
        collision_state = cmds.ls(type="joint", long=True)
        with self.assertRaises(ValueError):
            joint_duplicate.duplicate_hierarchy(root, "L_", "R_")

        self.assertEqual(3, len(before))
        self.assertEqual(collision_state, cmds.ls(type="joint", long=True))

    def test_non_joint_child_rejects_before_edit(self):
        root, _child, _tip = self._chain()
        cmds.createNode("transform", name="attachment", parent=root)
        before = cmds.ls(dagObjects=True, long=True)

        with self.assertRaises(ValueError):
            joint_duplicate.duplicate_hierarchy(root, "L_", "R_")

        self.assertEqual(before, cmds.ls(dagObjects=True, long=True))

    def test_invalid_planned_name_rejects_before_duplicate(self):
        root, _child, _tip = self._chain()
        before = cmds.ls(type="joint", long=True)

        with mock.patch.object(joint_duplicate.cmds, "duplicate") as duplicate:
            with self.assertRaises(ValueError):
                joint_duplicate.duplicate_hierarchy(root, "L_", "bad name")

        duplicate.assert_not_called()
        self.assertEqual(before, cmds.ls(type="joint", long=True))

    def test_rename_failure_rolls_back_duplicate(self):
        root, _child, _tip = self._chain()
        original_rename = joint_duplicate.cmds.rename
        calls = 0

        def fail_final(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 5:
                raise RuntimeError("expected failure")
            return original_rename(*args, **kwargs)

        with mock.patch.object(joint_duplicate.cmds, "rename", side_effect=fail_final):
            with self.assertRaises(RuntimeError):
                joint_duplicate.duplicate_hierarchy(root, "L_", "R_")

        self.assertEqual(3, len(cmds.ls(type="joint")))
        self.assertFalse(cmds.objExists("R_arm_jnt"))

    def test_options_window_builds(self):
        self.assertEqual("ywtaDuplicateJointHierarchyWindow", joint_duplicate.show_options())
