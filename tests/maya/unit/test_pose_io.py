"""Pose IO の Maya 単体テスト。"""

import copy

import maya.cmds as cmds

from ywta.anim import pose_io
from ywta.test import TestCase


class PoseIoTests(TestCase):
    """namespace 可搬 pose の主要 contract を検証する。"""

    def setUp(self):
        for option in (pose_io.BLEND_OPTION, pose_io.SELECTED_ONLY_OPTION):
            if cmds.optionVar(exists=option):
                cmds.optionVar(remove=option)

    def _control(self, namespace, name="hand_ctrl"):
        if namespace and not cmds.namespace(exists=namespace):
            cmds.namespace(add=namespace)
        prefix = namespace + ":" if namespace else ""
        node = cmds.createNode("transform", name=prefix + name)
        cmds.addAttr(node, longName="space", attributeType="enum", enumName="World:Chest", keyable=True)
        return node

    def test_pose_applies_across_namespaces(self):
        source = self._control("source")
        cmds.setAttr(source + ".translateX", 4.5)
        cmds.setAttr(source + ".rotateY", -12.0)
        data = pose_io.capture([source])
        cmds.delete(source)
        target = self._control("target")

        result = pose_io.apply(data)

        self.assertGreater(result["applied"], 0)
        self.assertAlmostEqual(4.5, cmds.getAttr(target + ".translateX"))
        self.assertAlmostEqual(-12.0, cmds.getAttr(target + ".rotateY"))

    def test_successful_apply_is_one_undo(self):
        source = self._control("source")
        cmds.setAttr(source + ".translateX", 4.5)
        cmds.setAttr(source + ".rotateY", -12.0)
        data = pose_io.capture([source])
        cmds.delete(source)
        target = self._control("target")

        pose_io.apply(data)
        cmds.undo()

        self.assertAlmostEqual(0.0, cmds.getAttr(target + ".translateX"))
        self.assertAlmostEqual(0.0, cmds.getAttr(target + ".rotateY"))

    def test_explicit_pose_id_survives_control_rename(self):
        source = self._control("source", "left_hand")
        pose_io.set_pose_id(source, "arm.left.ik")
        cmds.setAttr(source + ".translateZ", 7.0)
        data = pose_io.capture([source])
        cmds.delete(source)
        target = self._control("target", "renamed_hand")
        pose_io.set_pose_id(target, "arm.left.ik")

        pose_io.apply(data)

        self.assertAlmostEqual(7.0, cmds.getAttr(target + ".translateZ"))

    def test_pose_id_creation_is_one_undoable_action(self):
        """Pose ID属性の追加と値設定をまとめてUndo/Redoできる。"""
        control = self._control("character")

        plug = pose_io.set_pose_id(control, "arm.left.ik")
        self.assertEqual("arm.left.ik", cmds.getAttr(plug))
        cmds.undo()
        self.assertFalse(cmds.objExists(plug))
        cmds.redo()
        self.assertEqual("arm.left.ik", cmds.getAttr(plug))

    def test_pose_id_rejects_non_string_before_edit(self):
        """文字列以外のPose IDで属性を作成しない。"""
        control = self._control("character")

        with self.assertRaises(ValueError):
            pose_io.set_pose_id(control, 42)

        self.assertFalse(cmds.objExists(control + "." + pose_io.POSE_ID_ATTRIBUTE))

    def test_blend_and_enum_label(self):
        source = self._control("source")
        cmds.setAttr(source + ".translateX", 10.0)
        cmds.setAttr(source + ".space", 1)
        data = pose_io.capture([source])
        cmds.delete(source)
        target = self._control("target")

        pose_io.apply(data, blend=0.25)

        self.assertAlmostEqual(2.5, cmds.getAttr(target + ".translateX"))
        self.assertEqual(1, cmds.getAttr(target + ".space"))

    def test_selected_scope_does_not_touch_other_controls(self):
        source_a = self._control("source", "hand_ctrl")
        source_b = self._control("source", "foot_ctrl")
        cmds.setAttr(source_a + ".translateX", 2.0)
        cmds.setAttr(source_b + ".translateX", 3.0)
        data = pose_io.capture([source_a, source_b])
        cmds.delete(source_a, source_b)
        target_a = self._control("target", "hand_ctrl")
        target_b = self._control("target", "foot_ctrl")

        pose_io.apply(data, nodes=[target_a])

        self.assertAlmostEqual(2.0, cmds.getAttr(target_a + ".translateX"))
        self.assertAlmostEqual(0.0, cmds.getAttr(target_b + ".translateX"))

    def test_ambiguous_name_fails_before_edit(self):
        source = self._control("source")
        cmds.setAttr(source + ".translateX", 8.0)
        data = pose_io.capture([source])
        cmds.delete(source)
        first = self._control("first")
        second = self._control("second")

        with self.assertRaises(ValueError):
            pose_io.apply(data)

        self.assertEqual(0.0, cmds.getAttr(first + ".translateX"))
        self.assertEqual(0.0, cmds.getAttr(second + ".translateX"))

    def test_invalid_value_fails_before_edit(self):
        source = self._control("source")
        data = copy.deepcopy(pose_io.capture([source]))
        data["controls"][0]["attributes"][0]["value"] = float("nan")

        with self.assertRaises(ValueError):
            pose_io.apply(data)

    def test_save_and_read_round_trip(self):
        source = self._control("source")
        cmds.setAttr(source + ".translateY", 6.0)
        path = self.get_temp_filename("pose.json")

        pose_io.save([source], path)
        data = pose_io.read(path)

        self.assertEqual(pose_io.FORMAT, data["format"])
        self.assertEqual("name:hand_ctrl", data["controls"][0]["address"])
        self.assertEqual(cmds.currentUnit(query=True, linear=True), data["linear_unit"])
        self.assertEqual(cmds.currentUnit(query=True, angle=True), data["angle_unit"])

    def test_temporary_pose_round_trip_uses_validated_engine(self):
        source = self._control("source")
        cmds.setAttr(source + ".translateX", 7.5)
        path = self.get_temp_filename("temporary_pose.json")
        pose_io.save_temp([source], file_path=path)
        cmds.delete(source)
        target = self._control("target")

        result = pose_io.load_temp(nodes=[target], file_path=path)

        self.assertGreater(result["applied"], 0)
        self.assertAlmostEqual(7.5, cmds.getAttr(target + ".translateX"))

    def test_unit_mismatch_is_reported_without_value_conversion(self):
        source = self._control("source")
        cmds.setAttr(source + ".translateX", 5.0)
        data = pose_io.capture([source])
        data["linear_unit"] = "m" if cmds.currentUnit(query=True, linear=True) != "m" else "cm"
        cmds.delete(source)
        target = self._control("target")

        result = pose_io.apply(data, nodes=[target])

        self.assertEqual(["linear_unit"], result["unit_mismatches"])
        self.assertAlmostEqual(5.0, cmds.getAttr(target + ".translateX"))

    def test_animated_channel_is_keyed_at_current_time(self):
        source = self._control("source")
        cmds.setAttr(source + ".translateX", 5.0)
        data = pose_io.capture([source])
        cmds.delete(source)
        target = self._control("target")
        cmds.setKeyframe(target, attribute="translateX", time=1, value=0.0)
        cmds.currentTime(1)

        pose_io.apply(data)

        self.assertAlmostEqual(5.0, cmds.getAttr(target + ".translateX"))
        self.assertEqual([1.0], cmds.keyframe(target, attribute="translateX", query=True, timeChange=True))

    def test_computed_channel_is_skipped(self):
        source = self._control("source")
        cmds.setAttr(source + ".translateX", 5.0)
        data = pose_io.capture([source])
        cmds.delete(source)
        target = self._control("target")
        driver = cmds.createNode("multiplyDivide")
        cmds.setAttr(driver + ".input1X", 2.0)
        cmds.connectAttr(driver + ".outputX", target + ".translateX")

        result = pose_io.apply(data)

        skipped = [item for item in result["skipped"] if item.get("attribute") == "translateX"]
        self.assertEqual("driven", skipped[0]["reason"])
        self.assertAlmostEqual(2.0, cmds.getAttr(target + ".translateX"))

    def test_computed_channel_is_not_captured(self):
        source = self._control("source")
        driver = cmds.createNode("multiplyDivide")
        cmds.setAttr(driver + ".input1X", 3.0)
        cmds.connectAttr(driver + ".outputX", source + ".translateX")

        data = pose_io.capture([source])

        attributes = data["controls"][0]["attributes"]
        self.assertNotIn("translateX", [attribute["name"] for attribute in attributes])

    def test_enum_explicit_indices_are_resolved_by_label(self):
        source = self._control("source")
        cmds.addAttr(
            source,
            longName="mode",
            attributeType="enum",
            enumName="FK=1:IK=5",
            keyable=True,
        )
        cmds.setAttr(source + ".mode", 5)
        data = pose_io.capture([source])
        cmds.delete(source)
        target = self._control("target")
        cmds.addAttr(
            target,
            longName="mode",
            attributeType="enum",
            enumName="FK=1:IK=5",
            keyable=True,
        )

        pose_io.apply(data)

        self.assertEqual(5, cmds.getAttr(target + ".mode"))

    def test_load_settings_round_trip_and_invalid_blend_falls_back(self):
        self.assertEqual((1.0, False), pose_io.get_load_settings())
        self.assertEqual((0.25, True), pose_io.set_load_settings(0.25, True))
        self.assertEqual((0.25, True), pose_io.get_load_settings())

        cmds.optionVar(floatValue=(pose_io.BLEND_OPTION, 2.0))

        self.assertEqual((1.0, True), pose_io.get_load_settings())

    def test_load_options_window_builds(self):
        self.assertEqual("ywtaPoseLoadOptionsWindow", pose_io.show_load_options())
