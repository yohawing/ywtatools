"""Portable Selection Sets の Maya 単体テスト。"""

import copy

import maya.cmds as cmds

from ywta.anim import selection_sets
from ywta.test import TestCase


class SelectionSetsTests(TestCase):
    """objectSet と portable address の contract を検証する。"""

    def _control(self, namespace, name):
        if namespace and not cmds.namespace(exists=namespace):
            cmds.namespace(add=namespace)
        prefix = namespace + ":" if namespace else ""
        return cmds.createNode("transform", name=prefix + name)

    def test_create_list_and_select_members(self):
        hand = self._control("character", "hand_ctrl")
        foot = self._control("character", "foot_ctrl")

        node = selection_sets.create_selection_set("Limbs", [hand, foot])
        selected = selection_sets.select_members(node)

        self.assertEqual([node], selection_sets.list_selection_sets())
        self.assertEqual({hand, foot}, {value.rsplit("|", 1)[-1] for value in selected})

    def test_duplicate_label_is_rejected(self):
        hand = self._control("character", "hand_ctrl")
        selection_sets.create_selection_set("Hands", [hand])

        with self.assertRaises(ValueError):
            selection_sets.create_selection_set("hands", [hand])

    def test_import_label_is_trimmed_before_conflict_check(self):
        """外部labelの周辺空白で既存set衝突を回避できない。"""
        hand = self._control("character", "hand_ctrl")
        node = selection_sets.create_selection_set("Hands", [hand])
        data = copy.deepcopy(selection_sets.capture([node]))
        data["sets"][0]["label"] = "  Hands  "

        with self.assertRaises(ValueError):
            selection_sets.apply(data)

        self.assertEqual([node], selection_sets.list_selection_sets())

    def test_empty_portable_address_is_rejected_before_creation(self):
        """prefixだけのmember addressから空setを作成しない。"""
        hand = self._control("source", "hand_ctrl")
        node = selection_sets.create_selection_set("Hands", [hand])
        data = copy.deepcopy(selection_sets.capture([node]))
        data["sets"][0]["members"][0] = "name:"
        cmds.delete(node)

        with self.assertRaises(ValueError):
            selection_sets.apply(data)

        self.assertFalse(selection_sets.list_selection_sets())

    def test_create_is_single_undoable_action(self):
        hand = self._control("character", "hand_ctrl")

        node = selection_sets.create_selection_set("Hands", [hand])
        cmds.undo()
        self.assertFalse(cmds.objExists(node))
        cmds.redo()
        self.assertTrue(cmds.objExists(node))
        self.assertEqual([node], selection_sets.list_selection_sets())

    def test_delete_is_undoable(self):
        """削除したselection setを1回のUndoで復元できる。"""
        hand = self._control("character", "hand_ctrl")
        node = selection_sets.create_selection_set("Hands", [hand])

        selection_sets.delete_selection_set(node)
        self.assertFalse(cmds.objExists(node))
        cmds.undo()
        self.assertTrue(cmds.objExists(node))
        cmds.redo()
        self.assertFalse(cmds.objExists(node))

    def test_sets_apply_across_namespace(self):
        source_hand = self._control("source", "hand_ctrl")
        source_foot = self._control("source", "foot_ctrl")
        selection_sets.create_selection_set("Limbs", [source_hand, source_foot])
        data = selection_sets.capture()
        cmds.delete(selection_sets.list_selection_sets())
        cmds.delete(source_hand, source_foot)
        target_hand = self._control("target", "hand_ctrl")
        target_foot = self._control("target", "foot_ctrl")

        result = selection_sets.apply(data)

        self.assertEqual(1, len(result["created"]))
        self.assertEqual(
            {target_hand, target_foot},
            {value.rsplit("|", 1)[-1] for value in selection_sets.members(result["created"][0])},
        )

    def test_ambiguous_target_fails_before_set_creation(self):
        source = self._control("source", "hand_ctrl")
        selection_sets.create_selection_set("Hands", [source])
        data = selection_sets.capture()
        cmds.delete(selection_sets.list_selection_sets())
        cmds.delete(source)
        self._control("first", "hand_ctrl")
        self._control("second", "hand_ctrl")

        with self.assertRaises(ValueError):
            selection_sets.apply(data)

        self.assertFalse(selection_sets.list_selection_sets())

    def test_save_and_read_round_trip(self):
        hand = self._control("character", "hand_ctrl")
        selection_sets.create_selection_set("Hands", [hand])
        path = self.get_temp_filename("sets.json")

        selection_sets.save(path)
        data = selection_sets.read(path)

        self.assertEqual(selection_sets.FORMAT, data["format"])
        self.assertEqual("Hands", data["sets"][0]["label"])
