"""Rig Selection NavigationのMaya単体テスト。"""

import maya.cmds as cmds

from ywta.rig import selection_tools
from ywta.test import TestCase


class SelectionToolsTests(TestCase):
    """階層とskinCluster間の選択往復を検証する。"""

    def test_select_child_joints_excludes_root_and_keeps_hierarchy_order(self):
        root = cmds.joint(name="root_jnt")
        cmds.joint(name="child_jnt", position=(1.0, 0.0, 0.0))
        cmds.joint(name="grandchild_jnt", position=(2.0, 0.0, 0.0))

        result = selection_tools.select_child_joints([root])

        self.assertEqual(["child_jnt", "grandchild_jnt"], [node.rsplit("|", 1)[-1] for node in result])
        self.assertNotIn(root, result)

    def test_select_child_meshes_skips_intermediate_shapes(self):
        root = cmds.createNode("transform", name="asset_grp")
        mesh = cmds.polyCube(name="body_mesh")[0]
        cmds.parent(mesh, root)
        intermediate = cmds.createNode("mesh", name="bodyOrig", parent=mesh)
        cmds.setAttr(intermediate + ".intermediateObject", True)

        result = selection_tools.select_child_meshes([root])

        self.assertEqual(["body_mesh"], [node.rsplit("|", 1)[-1] for node in result])

    def test_skin_navigation_round_trip(self):
        mesh = cmds.polyPlane(name="cloth")[0]
        cmds.select(clear=True)
        root = cmds.joint(name="root_jnt")
        cmds.select(clear=True)
        tip = cmds.joint(name="tip_jnt", position=(1.0, 0.0, 0.0))
        cmds.skinCluster(root, tip, mesh, toSelectedBones=True)

        influences = selection_tools.select_influencing_joints([mesh])
        influenced = selection_tools.select_influenced_meshes([root])

        self.assertEqual({"root_jnt", "tip_jnt"}, {node.rsplit("|", 1)[-1] for node in influences})
        self.assertEqual(["cloth"], [node.rsplit("|", 1)[-1] for node in influenced])

    def test_unskinned_mesh_fails_without_changing_selection(self):
        mesh = cmds.polyCube(name="plain")[0]
        sentinel = cmds.spaceLocator(name="sentinel")[0]
        cmds.select(sentinel, replace=True)

        with self.assertRaises(ValueError):
            selection_tools.select_influencing_joints([mesh])

        self.assertEqual([sentinel], cmds.ls(selection=True))

    def test_snap_to_last_matches_world_pivot_and_is_undoable(self):
        """複数sourceをtarget pivotへ合わせ、1回のUndoで戻す。"""
        first = cmds.createNode("transform", name="first")
        second = cmds.createNode("transform", name="second")
        target = cmds.createNode("transform", name="target")
        cmds.setAttr(first + ".translate", 1.0, 2.0, 3.0)
        cmds.setAttr(second + ".translate", -2.0, 4.0, 1.0)
        cmds.setAttr(target + ".translate", 8.0, -1.0, 5.0)
        before = [cmds.xform(node, query=True, worldSpace=True, translation=True) for node in (first, second)]

        result = selection_tools.snap_to_last([first, second, target])

        expected = cmds.xform(target, query=True, worldSpace=True, rotatePivot=True)
        self.assertEqual(["first", "second"], [node.rsplit("|", 1)[-1] for node in result])
        for source in (first, second):
            self.assertEqual(expected, cmds.xform(source, query=True, worldSpace=True, rotatePivot=True))
        cmds.undo()
        self.assertEqual(before, [cmds.xform(node, query=True, worldSpace=True, translation=True) for node in (first, second)])

    def test_snap_rejects_locked_source_before_other_source_moves(self):
        """1つでもtranslate不可なら全sourceを編集しない。"""
        first = cmds.createNode("transform", name="first")
        locked = cmds.createNode("transform", name="locked")
        target = cmds.createNode("transform", name="target")
        cmds.setAttr(target + ".translateX", 5.0)
        cmds.setAttr(locked + ".translateX", lock=True)

        with self.assertRaises(ValueError):
            selection_tools.snap_to_last([first, locked, target])

        self.assertEqual(0.0, cmds.getAttr(first + ".translateX"))
