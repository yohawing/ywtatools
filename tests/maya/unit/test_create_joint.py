"""選択中心joint作成のMaya単体テスト。"""

import maya.cmds as cmds

from ywta.rig import create_joint
from ywta.test import TestCase


class CreateJointTests(TestCase):
    """位置、親子、Undo契約を検証する。"""

    def test_selected_components_create_one_joint_at_bounds_center(self):
        """複数component全体からjointを1つだけ作る。"""
        mesh = cmds.polyPlane(name="guide", width=4, height=2, subdivisionsX=2, subdivisionsY=1)[0]
        components = [mesh + ".vtx[0]", mesh + ".vtx[5]"]
        bounds = cmds.exactWorldBoundingBox(components)
        expected = [(bounds[index] + bounds[index + 3]) * 0.5 for index in range(3)]
        cmds.select(components, replace=True)

        result = create_joint.create_joint_at_selection(name="center_joint")

        self.assertEqual("|center_joint", result)
        self.assertEqual(1, len(cmds.ls(type="joint")))
        for actual, value in zip(cmds.xform(result, query=True, worldSpace=True, translation=True), expected):
            self.assertAlmostEqual(value, actual)

    def test_last_selected_joint_becomes_parent_and_undoes(self):
        """最後に選択したjointへparentし、1回のUndo/Redoで復元する。"""
        cmds.select(clear=True)
        parent = cmds.joint(name="parent_joint", position=(1, 2, 3))
        cmds.select(parent, replace=True)

        result = create_joint.create_joint_at_selection(name="child_joint")

        self.assertEqual("|parent_joint|child_joint", result)
        self.assertEqual(["parent_joint"], cmds.listRelatives(result, parent=True))
        cmds.undo()
        self.assertFalse(cmds.objExists("child_joint"))
        cmds.redo()
        self.assertTrue(cmds.objExists("|parent_joint|child_joint"))

    def test_empty_selection_creates_at_origin(self):
        """空選択ではworld原点へjointを作成する。"""
        cmds.select(clear=True)

        result = create_joint.create_joint_at_selection()

        self.assertEqual([0.0, 0.0, 0.0], cmds.xform(result, query=True, worldSpace=True, translation=True))

    def test_invalid_name_rejects_before_scene_edit(self):
        """不正名ではjointを作成しない。"""
        with self.assertRaises(ValueError):
            create_joint.create_joint_at_selection(name=" ")

        self.assertEqual([], cmds.ls(type="joint"))
