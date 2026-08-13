"""新規Maya変更操作のUndo guardテスト。"""

import maya.cmds as cmds

import ywta.name as name_tools
from ywta.core import undo_utils
from ywta.test import TestCase


class UndoUtilsTests(TestCase):
    """Undo無効時のfail-closed契約を検証する。"""

    def test_guard_accepts_enabled_undo(self):
        self.assertIsNone(undo_utils.require_enabled("test"))

    def test_name_tools_reject_before_edit_when_undo_is_disabled(self):
        node = cmds.createNode("transform", name="source")
        cmds.undoInfo(stateWithoutFlush=False)
        try:
            with self.assertRaises(RuntimeError):
                name_tools.rename_nodes([node], ["renamed"])
            self.assertTrue(cmds.objExists(node))
            self.assertFalse(cmds.objExists("renamed"))
        finally:
            cmds.undoInfo(stateWithoutFlush=True)
