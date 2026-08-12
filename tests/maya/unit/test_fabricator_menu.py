"""Fabricator参考Maya機能のメニュー到達性テスト。"""

import ast
import importlib

from unittest import mock

import maya.cmds as cmds

from ywta.menu import menu_animation
from ywta.menu import menu_deform
from ywta.menu import menu_rigging
from ywta.menu import menu_utility
from ywta.menu import core as menu_core
from ywta.test import TestCase


class FabricatorMenuTests(TestCase):
    """主要機能のmenu labelとPython command構文を固定する。"""

    ADOPTION_MODULES = {
        "ywta.anim.clip_io",
        "ywta.anim.pose_io",
        "ywta.anim.selection_sets",
        "ywta.deform.combine_skinned",
        "ywta.deform.influence_cleanup",
        "ywta.deform.separate_skinned",
        "ywta.deform.skin_influences",
        "ywta.deform.skin_io",
        "ywta.deform.skin_mirror",
        "ywta.deform.skin_smooth",
        "ywta.deform.skin_weights",
        "ywta.io.fbx_exporter",
        "ywta.name",
        "ywta.pipeline.batch_runner",
        "ywta.rig.constraint_tools",
        "ywta.rig.control",
        "ywta.rig.create_joint",
        "ywta.rig.create_object",
        "ywta.rig.joint_duplicate",
        "ywta.rig.joint_insert",
        "ywta.rig.joint_mirror",
        "ywta.rig.joint_orient",
        "ywta.rig.joint_size",
        "ywta.rig.selection_tools",
        "ywta.rig.skeleton_io",
        "ywta.utility.scene_audit",
    }

    @staticmethod
    def _resolve_reference(node, namespace):
        """AST上の名前参照を、呼び出さずに解決する。"""
        if isinstance(node, ast.Name):
            return namespace[node.id]
        if isinstance(node, ast.Attribute):
            return getattr(FabricatorMenuTests._resolve_reference(node.value, namespace), node.attr)
        raise TypeError("解決できないmenu command参照です: {}".format(ast.dump(node)))

    @classmethod
    def _assert_command_targets_exist(cls, command):
        """menu commandのimport先と呼び出し対象が存在することを確認する。"""
        tree = ast.parse(command, filename="<YWTA Menu Command>", mode="exec")
        namespace = {}
        for statement in tree.body:
            if not isinstance(statement, ast.Import):
                continue
            for imported in statement.names:
                if imported.name not in cls.ADOPTION_MODULES:
                    continue
                module = importlib.import_module(imported.name)
                if imported.asname:
                    namespace[imported.asname] = module
                else:
                    namespace[imported.name.split(".")[0]] = importlib.import_module(imported.name.split(".")[0])
        for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
            root = call.func
            while isinstance(root, ast.Attribute):
                root = root.value
            if not isinstance(root, ast.Name) or root.id not in namespace:
                continue
            target = cls._resolve_reference(call.func, namespace)
            if not callable(target):
                raise TypeError("menu commandの呼び出し対象がcallableではありません: {}".format(command))

    @staticmethod
    def _build(builder):
        calls = []

        def menu_item(*_args, **kwargs):
            calls.append(kwargs)
            return "ywtaMenuItem{}".format(len(calls))

        with mock.patch.object(cmds, "menuItem", side_effect=menu_item):
            builder("ywtaTestMenu")
        labels = {call.get("label") for call in calls if call.get("label")}
        commands = [call["command"] for call in calls if isinstance(call.get("command"), str)]
        for command in commands:
            FabricatorMenuTests._assert_command_targets_exist(command)
        return labels

    def test_rigging_adoption_entries_are_reachable(self):
        labels = self._build(menu_rigging.create_rigging_menu)

        self.assertTrue(
            {
                "Name Tools",
                "Rename Chain",
                "Create Joint",
                "Insert Joints Between Selected...",
                "Orient Selected Joints to Children",
                "Duplicate Joint Hierarchy...",
                "Create at Selection Center",
                "Null",
                "Locator",
                "Poly Cube",
                "Poly Sphere",
                "Poly Cylinder",
                "Poly Plane",
                "Constraints",
                "Create Constraint...",
                "Parent Constraint",
                "Point Constraint",
                "Orient Constraint",
                "Scale Constraint",
                "Aim Constraint",
                "Delete Constraints",
                "Mirror Joint Hierarchy (Static YZ)",
                "Joint Size Tools",
                "Export Skeleton",
                "Import Skeleton",
                "Import Skeleton (Bake Rotate to Joint Orient)",
                "Import Skeleton (Clean Joint TRS)",
                "Save Temporary Skeleton",
                "Load Temporary Skeleton",
                "Load Temporary Skeleton (Clean Joint TRS)",
                "Control Creator",
                "Import Control Curves",
                "Swap Selected Control Shapes",
                "Mirror Selected Control Shape",
                "Edit Selected Control CVs",
                "Combine Selected Control Shapes",
                "Select Child Joints",
                "Select Child Meshes",
                "Select Influencing Joints",
                "Select Influenced Meshes",
                "Snap A to B (Position)",
            }.issubset(labels)
        )

    def test_deform_adoption_entries_are_reachable(self):
        labels = self._build(menu_deform.create_deform_menu)

        self.assertTrue(
            {
                "Save Skin Weights",
                "Load Skin Weights (Same Topology)",
                "Load Skin Weights to Selected Vertices",
                "Transfer Skin Weights (Configured)",
                "Skin Transfer Options...",
                "Save Temporary Skin Weights",
                "Load Temporary Skin Weights (Direct)",
                "Transfer Temporary Skin Weights (Configured)",
                "Copy Vertex Weights",
                "Copy Average Vertex Weights",
                "Paste Vertex Weights",
                "Average Vertex Weights",
                "Add Selected Skin Influences",
                "Remove Selected Unused Influences",
                "Mirror Skin Weights +X to -X",
                "Mirror Skin Weights -X to +X",
                "Smooth Selected Skin Weights",
                "Remove Unused Skin Influences",
                "Combine Skinned Meshes",
                "Separate Skinned Mesh Shells",
            }.issubset(labels)
        )

    def test_animation_adoption_entries_are_reachable(self):
        labels = self._build(menu_animation.create_animation_menu)

        self.assertTrue(
            {
                "Selection Sets",
                "Set Pose ID...",
                "Save Selected Pose",
                "Load Pose",
                "Load Pose to Selected",
                "Save Temporary Pose",
                "Load Temporary Pose (Configured)",
                "Save Selected Animation Clip",
                "Load Animation Clip (Configured)",
                "Load Animation Clip (Replace)",
                "Load Animation Clip (Place)",
                "Load Animation Clip (Insert)",
                "Load Animation Clip to Selected (Replace)",
                "Save Temporary Animation Clip",
                "Load Temporary Animation Clip (Configured)",
            }.issubset(labels)
        )

    def test_scene_audit_is_reachable(self):
        labels = self._build(menu_utility.create_utility_menu)

        self.assertIn("Scene Audit", labels)

    def test_top_level_batch_and_fbx_entries_are_reachable(self):
        calls = []

        def menu_item(*_args, **kwargs):
            calls.append(kwargs)
            return "ywtaTopItem{}".format(len(calls))

        with (
            mock.patch.object(cmds, "menu", return_value="ywtaTestMenu"),
            mock.patch.object(cmds, "menuItem", side_effect=menu_item),
            mock.patch.object(menu_core, "delete_menu"),
            mock.patch.object(menu_core.mel, "eval", return_value="MayaWindow"),
            mock.patch.object(menu_core.menu_animation, "create_animation_menu"),
            mock.patch.object(menu_core.menu_mesh, "create_mesh_menu"),
            mock.patch.object(menu_core.menu_rigging, "create_rigging_menu"),
            mock.patch.object(menu_core.menu_deform, "create_deform_menu"),
            mock.patch.object(menu_core.menu_utility, "create_utility_menu"),
        ):
            menu_core.create_menu()

        labels = {call.get("label") for call in calls if call.get("label")}
        self.assertTrue(
            {
                "Batch Runner",
                "Export Selected FBX",
                "Export Animation FBX",
            }.issubset(labels)
        )
        for call in calls:
            if isinstance(call.get("command"), str):
                self._assert_command_targets_exist(call["command"])
