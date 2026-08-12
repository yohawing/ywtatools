"""Fabricator参考Maya機能のメニュー到達性テスト。"""

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
            compile(command, "<YWTA Menu Command>", "exec")
        return labels

    def test_rigging_adoption_entries_are_reachable(self):
        labels = self._build(menu_rigging.create_rigging_menu)

        self.assertTrue(
            {
                "Name Tools",
                "Rename Chain",
                "Create Joint",
                "Insert Joints Between Selected...",
                "Create at Selection Center",
                "Null",
                "Locator",
                "Poly Cube",
                "Poly Sphere",
                "Poly Cylinder",
                "Poly Plane",
                "Constraints",
                "Parent Constraint",
                "Point Constraint",
                "Orient Constraint",
                "Scale Constraint",
                "Aim Constraint",
                "Delete Constraints",
                "Mirror Joint Hierarchy (Static YZ)",
                "Export Skeleton",
                "Import Skeleton",
                "Import Skeleton (Clean Joint TRS)",
                "Save Temporary Skeleton",
                "Load Temporary Skeleton",
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
                "Transfer Skin Weights (Closest Point)",
                "Save Temporary Skin Weights",
                "Copy Vertex Weights",
                "Copy Average Vertex Weights",
                "Add Selected Skin Influences",
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
                "Save Selected Pose",
                "Load Pose",
                "Save Temporary Pose",
                "Load Temporary Pose (Configured)",
                "Save Selected Animation Clip",
                "Load Animation Clip (Configured)",
                "Load Animation Clip (Insert)",
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
                compile(call["command"], "<YWTA Menu Command>", "exec")
