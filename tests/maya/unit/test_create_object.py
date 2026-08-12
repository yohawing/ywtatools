"""基本object作成ツールのMaya単体テスト。"""

import maya.cmds as cmds

from ywta.rig import create_object
from ywta.test import TestCase


class CreateObjectTests(TestCase):
    """object種別、位置、Undoを検証する。"""

    def test_all_supported_types_create_expected_shapes(self):
        """各種別を原点へ作成し、期待するshape typeを持たせる。"""
        expected_shapes = {
            "null": None,
            "locator": "locator",
            "cube": "mesh",
            "sphere": "mesh",
            "cylinder": "mesh",
            "plane": "mesh",
        }
        for kind, expected_shape in expected_shapes.items():
            cmds.select(clear=True)
            transform = create_object.create_at_selection(kind, name="{}_test".format(kind))
            shapes = cmds.listRelatives(transform, shapes=True, noIntermediate=True, fullPath=True) or []
            self.assertEqual(expected_shape, cmds.nodeType(shapes[0]) if shapes else None)
            self.assertEqual([0.0, 0.0, 0.0], cmds.xform(transform, query=True, worldSpace=True, translation=True))

    def test_object_uses_selection_bounds_center_and_undoes(self):
        """選択全体の中心へ作成し、1回のUndo/Redoで復元する。"""
        guide = cmds.polyCube(name="guide", width=2, height=4, depth=6)[0]
        cmds.setAttr(guide + ".translate", 3.0, -2.0, 5.0)
        cmds.select(guide, replace=True)

        result = create_object.create_at_selection("locator", name="center_locator")

        self.assertEqual([3.0, -2.0, 5.0], cmds.xform(result, query=True, worldSpace=True, translation=True))
        cmds.undo()
        self.assertFalse(cmds.objExists("center_locator"))
        cmds.redo()
        self.assertTrue(cmds.objExists("center_locator"))

    def test_invalid_kind_rejects_before_scene_edit(self):
        """未対応種別ではnodeを作成しない。"""
        before = set(cmds.ls())

        with self.assertRaises(ValueError):
            create_object.create_at_selection("torus")

        self.assertEqual(before, set(cmds.ls()))
