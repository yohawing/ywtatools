"""選択中心joint作成のMaya単体テスト。"""

from unittest import mock

import maya.cmds as cmds

from ywta.rig import create_joint, joint_edit_tools
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

    def test_name_is_deterministic_and_parent_namespace_is_inherited(self):
        """単純名はparent namespaceを継承し、親なしではrootへ作成する。"""
        cmds.namespace(add="character")
        cmds.namespace(add="working")
        cmds.select(clear=True)
        parent = cmds.joint(name=":character:parent_joint")
        cmds.namespace(set="working")
        cmds.select(parent, replace=True)

        child = create_joint.create_joint_at_selection(name="child_joint")
        cmds.select(clear=True)
        root = create_joint.create_joint_at_selection(name="root_joint")
        cmds.namespace(set=":")

        self.assertEqual("|character:parent_joint|character:child_joint", child)
        self.assertEqual("|root_joint", root)
        self.assertFalse(cmds.objExists(":working:root_joint"))

    def test_sanitized_name_and_missing_namespace_reject_before_undo(self):
        """不正名と未作成namespaceではUndo queueを要求しない。"""
        cmds.undoInfo(stateWithoutFlush=False)
        try:
            for invalid in ("bad name", "1joint", "joint#", "joint-name", "missing:joint"):
                with self.assertRaises(ValueError):
                    create_joint.create_joint_at_selection(name=invalid)
        finally:
            cmds.undoInfo(stateWithoutFlush=True)

        self.assertEqual([], cmds.ls(type="joint"))

    def test_legacy_vertex_entry_uses_arithmetic_average(self):
        """旧vertex APIはbounding boxではなく選択頂点平均を維持する。"""
        mesh = cmds.polyCreateFacet(point=[(0, 0, 0), (9, 0, 0), (0, 3, 0)])[0]
        cmds.select(mesh + ".vtx[0:2]", replace=True)

        joint = create_joint.create_joint_from_selected_verts()

        self.assertEqual([3.0, 1.0, 0.0], cmds.xform(joint, query=True, worldSpace=True, translation=True))

    def test_legacy_face_entry_creates_one_joint_per_face(self):
        """旧face APIは各face中心へ別jointを作成する。"""
        mesh = cmds.polyPlane(subdivisionsX=2, subdivisionsY=1)[0]
        cmds.select(mesh + ".f[0:1]", replace=True)

        joints = create_joint.create_joint_from_selected_faces()

        self.assertEqual(2, len(joints))
        cmds.undo()
        self.assertFalse(any(cmds.objExists(joint) for joint in joints))

    def test_joint_edit_tools_routes_create_through_safe_entry(self):
        """旧windowのAdd Jointも選択中心とUndoの共通経路を使う。"""
        window = joint_edit_tools.JointEditToolsWindow.__new__(joint_edit_tools.JointEditToolsWindow)
        window.create_joint_field = "nameField"

        with (
            mock.patch.object(joint_edit_tools.cmds, "textField", return_value="helper_jnt"),
            mock.patch.object(
                joint_edit_tools.create_joint,
                "create_joint_at_selection",
                return_value="|helper_jnt",
            ) as create_at_selection,
        ):
            window._create_joint(False)

        create_at_selection.assert_called_once_with(name="helper_jnt")
