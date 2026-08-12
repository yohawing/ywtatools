"""Name Tools の Maya 単体テスト。"""

import maya.cmds as cmds

import ywta.name as name_tools
from ywta.test import TestCase


class NameToolsTests(TestCase):
    """一括名前変更の主要な振る舞いを検証する。"""

    def test_hash_rename_preserves_selection_order(self):
        first = cmds.createNode("transform", name="first")
        second = cmds.createNode("transform", name="second")

        result = name_tools.hash_rename("ctrl_##", [second, first], start=3)

        self.assertEqual(["ctrl_03", "ctrl_04"], [node.rsplit("|", 1)[-1] for node in result])

    def test_parent_and_child_can_be_renamed_together(self):
        parent = cmds.createNode("transform", name="old_parent")
        child = cmds.createNode("transform", name="old_child", parent=parent)

        result = name_tools.rename_nodes([parent, child], ["new_parent", "new_child"])

        self.assertEqual("|new_parent", result[0])
        self.assertEqual("|new_parent|new_child", result[1])

    def test_successful_batch_is_one_undo(self):
        first = cmds.createNode("transform", name="first")
        second = cmds.createNode("transform", name="second")

        name_tools.rename_nodes([first, second], ["renamed_first", "renamed_second"])
        cmds.undo()

        self.assertTrue(cmds.objExists("first"))
        self.assertTrue(cmds.objExists("second"))
        self.assertFalse(cmds.objExists("renamed_first"))
        self.assertFalse(cmds.objExists("renamed_second"))

    def test_find_replace_can_ignore_case(self):
        node = cmds.createNode("transform", name="Left_Arm_CTRL")

        result = name_tools.find_replace("left", "right", [node], case_sensitive=False)

        self.assertEqual("right_Arm_CTRL", result[0].rsplit("|", 1)[-1])

    def test_noop_find_replace_does_not_require_undo(self):
        """全件no-opの検索置換はscene編集を開始しない。"""
        node = cmds.createNode("transform", name="hand_ctrl")
        cmds.select(node, replace=True)
        cmds.undoInfo(stateWithoutFlush=False)
        try:
            result = name_tools.find_replace("missing", "other", [node])
        finally:
            cmds.undoInfo(stateWithoutFlush=True)

        self.assertEqual(["|hand_ctrl"], result)
        self.assertEqual([node], cmds.ls(selection=True))

    def test_affixes_preserve_namespace(self):
        cmds.namespace(add="character")
        node = cmds.createNode("transform", name="character:hand")

        result = name_tools.add_affixes("L_", "_jnt", [node])

        self.assertEqual("character:L_hand_jnt", result[0].rsplit("|", 1)[-1])

    def test_rename_is_independent_of_current_namespace(self):
        """元namespaceとroot nodeをcurrent namespaceへ誤移動しない。"""
        cmds.namespace(add="character")
        cmds.namespace(add="working")
        character_node = cmds.createNode("transform", name=":character:old")
        root_node = cmds.createNode("transform", name=":root_old")
        cmds.namespace(set="working")

        character_result = name_tools.hash_rename("new_##", [character_node])
        root_result = name_tools.rename_nodes([root_node], ["root_new"])
        cmds.namespace(set=":")

        self.assertEqual("character:new_01", character_result[0].rsplit("|", 1)[-1])
        self.assertEqual("root_new", root_result[0].rsplit("|", 1)[-1])
        self.assertFalse(cmds.objExists(":working:new_01"))
        self.assertFalse(cmds.objExists(":working:root_new"))

    def test_renumber_replaces_existing_trailing_number(self):
        nodes = [
            cmds.createNode("transform", name="finger_12"),
            cmds.createNode("transform", name="thumb"),
        ]

        result = name_tools.renumber(nodes, separator="_", padding=3, start=5)

        self.assertEqual(["finger_005", "thumb_006"], [node.rsplit("|", 1)[-1] for node in result])

    def test_invalid_numbering_options_fail_before_edit(self):
        """boolや非整数の番号設定でnode名を変えない。"""
        node = cmds.createNode("transform", name="original")

        with self.assertRaises(ValueError):
            name_tools.hash_rename("ctrl_##", [node], start=True)
        with self.assertRaises(ValueError):
            name_tools.renumber([node], padding="2")

        self.assertTrue(cmds.objExists("original"))

    def test_missing_explicit_node_rejects_partial_rename(self):
        """明示入力の欠落を落として残りだけ改名しない。"""
        node = cmds.createNode("transform", name="original")

        with self.assertRaises(ValueError):
            name_tools.hash_rename("renamed_##", [node, "missing_node"])

        self.assertTrue(cmds.objExists("original"))
        self.assertFalse(cmds.objExists("renamed_01"))

    def test_ambiguous_explicit_node_rejects_partial_rename(self):
        """曖昧な短名を複数対象として暗黙展開しない。"""
        first_parent = cmds.createNode("transform", name="first_parent")
        second_parent = cmds.createNode("transform", name="second_parent")
        cmds.createNode("transform", name="control", parent=first_parent)
        cmds.createNode("transform", name="control", parent=second_parent)

        with self.assertRaises(ValueError):
            name_tools.add_affixes(prefix="new_", nodes=["control"])

        self.assertEqual(2, len(cmds.ls("control", long=True)))
        self.assertFalse(cmds.ls("new_control", long=True))

    def test_duplicate_target_names_are_rejected_before_edit(self):
        first = cmds.createNode("transform", name="first")
        second = cmds.createNode("transform", name="second")

        with self.assertRaises(ValueError):
            name_tools.rename_nodes([first, second], ["same", "same"])

        self.assertTrue(cmds.objExists(first))
        self.assertTrue(cmds.objExists(second))

    def test_duplicate_source_node_is_rejected_before_edit(self):
        """同一nodeを複数回指定した曖昧なrenameを拒否する。"""
        node = cmds.createNode("transform", name="original")

        with self.assertRaises(ValueError):
            name_tools.rename_nodes([node, node], ["first", "second"])

        self.assertTrue(cmds.objExists("original"))
        self.assertFalse(cmds.objExists("first"))
        self.assertFalse(cmds.objExists("second"))

    def test_external_name_collision_rolls_back_batch(self):
        first = cmds.createNode("transform", name="first")
        second = cmds.createNode("transform", name="second")
        cmds.createNode("transform", name="occupied")

        with self.assertRaises(RuntimeError):
            name_tools.rename_nodes([first, second], ["renamed", "occupied"])

        self.assertTrue(cmds.objExists("first"))
        self.assertTrue(cmds.objExists("second"))
        self.assertFalse(cmds.objExists("renamed"))

    def test_select_by_name_unions_patterns_without_duplicates(self):
        left = cmds.createNode("transform", name="arm_L_jnt")
        right = cmds.createNode("transform", name="arm_R_jnt")
        cmds.createNode("transform", name="spine_ctrl")

        result = name_tools.select_by_name("*_L_jnt *_R_jnt *_L_jnt")

        self.assertEqual({left, right}, {node.rsplit("|", 1)[-1] for node in result})
