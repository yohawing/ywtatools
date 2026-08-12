"""選択順constraintツールのMaya単体テスト。"""

import maya.cmds as cmds

from ywta.rig import constraint_tools
from ywta.test import TestCase


class ConstraintToolsTests(TestCase):
    """作成、削除、Undo、事前検証を確認する。"""

    def test_selected_parent_constraint_preserves_selection_and_undoes(self):
        """最後の選択をdrivenとしてParent constraintを作成する。"""
        driver = cmds.spaceLocator(name="driver")[0]
        driven = cmds.spaceLocator(name="driven")[0]
        cmds.select(driver, driven, replace=True)

        constraint = constraint_tools.create_selected("parent", maintain_offset=False)

        self.assertEqual("parentConstraint", cmds.nodeType(constraint))
        self.assertEqual([driver, driven], cmds.ls(selection=True))
        cmds.setAttr(driver + ".translateX", 3.0)
        self.assertAlmostEqual(3.0, cmds.getAttr(driven + ".translateX"))
        cmds.undo()
        self.assertTrue(cmds.objExists(constraint))
        cmds.undo()
        self.assertFalse(cmds.objExists(constraint))
        cmds.redo()
        self.assertTrue(cmds.objExists(constraint))

    def test_all_constraint_types_create_expected_nodes(self):
        """公開する5種のconstraint commandを実行できる。"""
        for kind in ("parent", "point", "orient", "scale", "aim"):
            driver = cmds.spaceLocator(name="{}_driver".format(kind))[0]
            driven = cmds.spaceLocator(name="{}_driven".format(kind))[0]

            constraint = constraint_tools.create_constraint(kind, [driver], driven, maintain_offset=False)

            self.assertEqual(kind + "Constraint", cmds.nodeType(constraint))

    def test_locked_driven_channel_rejects_before_edit(self):
        """必要channelがlockedならconstraintを作成しない。"""
        driver = cmds.spaceLocator(name="driver")[0]
        driven = cmds.spaceLocator(name="driven")[0]
        cmds.setAttr(driven + ".translateX", lock=True)

        with self.assertRaises(ValueError):
            constraint_tools.create_constraint("point", [driver], driven)

        self.assertEqual([], cmds.ls(type="pointConstraint"))

    def test_delete_constraints_is_undoable(self):
        """drivenへ入るconstraintだけを削除してUndoできる。"""
        driver = cmds.spaceLocator(name="driver")[0]
        driven = cmds.spaceLocator(name="driven")[0]
        constraint = constraint_tools.create_constraint("orient", [driver], driven)
        sentinel = cmds.spaceLocator(name="sentinel")[0]
        cmds.select(driven, sentinel, replace=True)

        removed = constraint_tools.delete_constraints([driven])

        self.assertIn(constraint.rsplit("|", 1)[-1], removed)
        self.assertFalse(cmds.objExists(constraint))
        self.assertEqual([driven, sentinel], cmds.ls(selection=True))
        cmds.undo()
        self.assertTrue(cmds.objExists(constraint))
