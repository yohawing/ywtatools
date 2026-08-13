"""Static Joint Hierarchy MirrorのMaya単体テスト。"""

from unittest import mock

import maya.cmds as cmds

from ywta.rig import joint_edit_tools, joint_mirror
from ywta.test import TestCase


class JointMirrorTests(TestCase):
    """命名、階層、衝突拒否、Undoを検証する。"""

    def _chain(self, namespace=""):
        if namespace and not cmds.namespace(exists=namespace):
            cmds.namespace(add=namespace)
        prefix = namespace + ":" if namespace else ""
        cmds.select(clear=True)
        root = cmds.joint(name=prefix + "L_arm_jnt", position=(2.0, 0.0, 0.0))
        child = cmds.joint(name=prefix + "L_elbow_jnt", position=(4.0, 1.0, 0.0))
        return root, child

    def test_mirror_preserves_hierarchy_namespace_and_behavior(self):
        root, _child = self._chain("char")

        created = joint_mirror.mirror_hierarchy(root)

        self.assertEqual("char:R_arm_jnt", created[0].rsplit("|", 1)[-1])
        self.assertEqual("char:R_elbow_jnt", created[1].rsplit("|", 1)[-1])
        self.assertEqual(created[0], cmds.listRelatives(created[1], parent=True, fullPath=True)[0])
        self.assertEqual([-2.0, 0.0, 0.0], cmds.xform(created[0], query=True, worldSpace=True, translation=True))
        self.assertEqual([-4.0, 1.0, 0.0], cmds.xform(created[1], query=True, worldSpace=True, translation=True))

    def test_mirror_is_independent_of_current_namespace(self):
        root, _child = self._chain("char")
        cmds.namespace(add="working")
        cmds.namespace(set="working")

        created = joint_mirror.mirror_hierarchy(root)
        cmds.namespace(set=":")

        self.assertEqual("char:R_arm_jnt", created[0].rsplit("|", 1)[-1])
        self.assertFalse(cmds.objExists(":working:char:R_arm_jnt"))

    def test_mirror_is_one_undoable_action(self):
        root, _child = self._chain()

        created = joint_mirror.mirror_hierarchy(root)
        root_uuid = cmds.ls(created[0], uuid=True)[0]
        cmds.undo()

        self.assertFalse(cmds.ls(root_uuid, uuid=True))
        self.assertTrue(cmds.objExists(root))
        cmds.redo()
        self.assertTrue(cmds.ls(root_uuid, uuid=True))
        self.assertEqual("R_arm_jnt", cmds.ls(selection=True)[0])

    def test_missing_side_token_fails_before_edit(self):
        cmds.select(clear=True)
        root = cmds.joint(name="arm_jnt", position=(2.0, 0.0, 0.0))

        with self.assertRaises(ValueError):
            joint_mirror.mirror_hierarchy(root)

        self.assertEqual([root], cmds.ls(type="joint"))

    def test_existing_target_collision_fails_before_edit(self):
        root, _child = self._chain()
        cmds.select(clear=True)
        cmds.joint(name="R_arm_jnt", position=(-2.0, 0.0, 0.0))
        before = cmds.ls(type="joint", long=True)

        with self.assertRaises(ValueError):
            joint_mirror.mirror_hierarchy(root)

        self.assertEqual(before, cmds.ls(type="joint", long=True))

    def test_child_without_side_token_fails_before_edit(self):
        cmds.select(clear=True)
        root = cmds.joint(name="L_arm_jnt", position=(2.0, 0.0, 0.0))
        cmds.joint(name="elbow_jnt", position=(4.0, 1.0, 0.0))
        before = cmds.ls(type="joint", long=True)

        with self.assertRaises(ValueError):
            joint_mirror.mirror_hierarchy(root)

        self.assertEqual(before, cmds.ls(type="joint", long=True))

    def test_non_joint_child_fails_before_undo_requirement(self):
        """mirrorJointが補助DAG nodeを複製する前に階層を拒否する。"""
        root, _child = self._chain()
        helper = cmds.spaceLocator(name="attachment")[0]
        cmds.parent(helper, root)
        before = cmds.ls(long=True)

        cmds.undoInfo(stateWithoutFlush=False)
        try:
            with self.assertRaises(ValueError):
                joint_mirror.mirror_hierarchy(root)
        finally:
            cmds.undoInfo(stateWithoutFlush=True)

        self.assertEqual(before, cmds.ls(long=True))
        self.assertFalse(cmds.objExists("R_arm_jnt"))

    def test_mid_rename_failure_rolls_back_created_hierarchy(self):
        root, _child = self._chain()
        original_rename = cmds.rename
        calls = {"count": 0}

        def fail_second_final_rename(*args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 4:
                raise RuntimeError("expected rename failure")
            return original_rename(*args, **kwargs)

        with mock.patch.object(cmds, "rename", side_effect=fail_second_final_rename):
            with self.assertRaises(RuntimeError):
                joint_mirror.mirror_hierarchy(root)

        self.assertEqual(2, len(cmds.ls(type="joint")))
        self.assertTrue(cmds.objExists("L_arm_jnt"))
        self.assertFalse(cmds.objExists("R_arm_jnt"))

    def test_mid_chain_root_is_parented_under_mirrored_parent(self):
        cmds.select(clear=True)
        left_parent = cmds.joint(name="L_shoulder_jnt", position=(1.0, 0.0, 0.0))
        left_root = cmds.joint(name="L_arm_jnt", position=(2.0, 0.0, 0.0))
        cmds.select(clear=True)
        right_parent = cmds.joint(name="R_shoulder_jnt", position=(-1.0, 0.0, 0.0))

        created = joint_mirror.mirror_hierarchy(left_root)

        self.assertEqual(
            cmds.ls(right_parent, long=True)[0],
            cmds.listRelatives(created[0], parent=True, fullPath=True)[0],
        )
        self.assertTrue(cmds.objExists(left_parent))

    def test_mid_chain_without_mirrored_parent_fails_before_edit(self):
        cmds.select(clear=True)
        cmds.joint(name="L_shoulder_jnt", position=(1.0, 0.0, 0.0))
        left_root = cmds.joint(name="L_arm_jnt", position=(2.0, 0.0, 0.0))
        before = cmds.ls(type="joint", long=True)

        with self.assertRaises(ValueError):
            joint_mirror.mirror_hierarchy(left_root)

        self.assertEqual(before, cmds.ls(type="joint", long=True))

    def test_side_token_styles_round_trip(self):
        self.assertEqual("Right_hand", joint_mirror.mirrored_name("Left_hand"))
        self.assertEqual("arm_r_jnt", joint_mirror.mirrored_name("arm_l_jnt"))
        self.assertEqual("char:rt_leg", joint_mirror.mirrored_name("char:lf_leg"))

    def test_joint_edit_tools_routes_mirror_through_safe_entry(self):
        """旧windowのMirror Jointも原子的な階層mirrorを使う。"""
        window = joint_edit_tools.JointEditToolsWindow.__new__(joint_edit_tools.JointEditToolsWindow)

        with mock.patch.object(
            joint_edit_tools.joint_mirror,
            "mirror_selected_hierarchy",
            return_value=["R_root", "R_child"],
        ) as mirror_selected:
            window._mirror_joint()

        mirror_selected.assert_called_once_with()
