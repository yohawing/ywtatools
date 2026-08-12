"""Animation Clip IO の Maya 単体テスト。"""

import copy

import maya.cmds as cmds

from ywta.anim import clip_io
from ywta.test import TestCase


class ClipIoTests(TestCase):
    """namespace 可搬 clip の保存・適用 contract を検証する。"""

    def setUp(self):
        for option in (
            clip_io.MODE_OPTION,
            clip_io.SELECTED_ONLY_OPTION,
            clip_io.START_ANCHOR_OPTION,
            clip_io.END_ANCHOR_OPTION,
        ):
            if cmds.optionVar(exists=option):
                cmds.optionVar(remove=option)

    def _control(self, namespace, name="hand_ctrl"):
        if namespace and not cmds.namespace(exists=namespace):
            cmds.namespace(add=namespace)
        prefix = namespace + ":" if namespace else ""
        return cmds.createNode("transform", name=prefix + name)

    def _source_clip(self):
        source = self._control("source")
        cmds.setKeyframe(source, attribute="translateX", time=10, value=1.0, inTangentType="linear", outTangentType="linear")
        cmds.setKeyframe(source, attribute="translateX", time=20, value=5.0, inTangentType="flat", outTangentType="flat")
        return source, clip_io.capture([source], start=10, end=20)

    def test_clip_applies_across_namespace_with_offset(self):
        source, data = self._source_clip()
        cmds.delete(source)
        target = self._control("target")

        result = clip_io.apply(data, start_time=100)

        self.assertEqual(1, result["applied_channels"])
        self.assertEqual([100.0, 110.0], cmds.keyframe(target, attribute="translateX", query=True, timeChange=True))
        self.assertEqual([1.0, 5.0], cmds.keyframe(target, attribute="translateX", query=True, valueChange=True))
        self.assertEqual(
            ["linear", "flat"],
            cmds.keyTangent(target, attribute="translateX", query=True, inTangentType=True),
        )

    def test_replace_removes_keys_only_inside_clip_range(self):
        source, data = self._source_clip()
        cmds.delete(source)
        target = self._control("target")
        cmds.setKeyframe(target, attribute="translateX", time=90, value=-1.0)
        cmds.setKeyframe(target, attribute="translateX", time=105, value=-2.0)
        cmds.setKeyframe(target, attribute="translateX", time=120, value=-3.0)

        clip_io.apply(data, start_time=100, replace=True)

        self.assertEqual(
            [90.0, 100.0, 110.0, 120.0],
            cmds.keyframe(target, attribute="translateX", query=True, timeChange=True),
        )

    def test_place_preserves_existing_keys_inside_clip_range(self):
        source, data = self._source_clip()
        cmds.delete(source)
        target = self._control("target")
        cmds.setKeyframe(target, attribute="translateX", time=105, value=-2.0)

        result = clip_io.apply(data, nodes=[target], start_time=100, mode="place")

        self.assertEqual("place", result["mode"])
        self.assertEqual(
            [100.0, 105.0, 110.0],
            cmds.keyframe(target, attribute="translateX", query=True, timeChange=True),
        )

    def test_capture_adds_optional_synthetic_boundary_anchors(self):
        source = self._control("source")
        cmds.setKeyframe(source, attribute="translateX", time=5, value=5.0)
        data = clip_io.capture([source], start=1, end=10)
        keys = data["controls"][0]["channels"][0]["keys"]

        self.assertEqual([0.0, 4.0, 9.0], [key["time"] for key in keys])
        self.assertEqual("start", keys[0]["synthetic_boundary"])
        self.assertNotIn("synthetic_boundary", keys[1])
        self.assertEqual("end", keys[2]["synthetic_boundary"])

    def test_synthetic_boundary_anchors_can_be_skipped(self):
        source = self._control("source")
        cmds.setKeyframe(source, attribute="translateX", time=5, value=5.0)
        data = clip_io.capture([source], start=1, end=10)
        cmds.delete(source)
        target = self._control("target")

        result = clip_io.apply(
            data,
            nodes=[target],
            start_time=20,
            apply_start_anchor=False,
            apply_end_anchor=False,
        )

        self.assertEqual(1, result["applied_keys"])
        self.assertEqual(
            [24.0],
            cmds.keyframe(target, attribute="translateX", query=True, timeChange=True),
        )

    def test_insert_shifts_all_keys_on_resolved_control_and_is_undoable(self):
        source, data = self._source_clip()
        cmds.delete(source)
        target = self._control("target")
        other = self._control("target", "other_ctrl")
        cmds.setKeyframe(target, attribute="rotateZ", time=100, value=9.0)
        cmds.setKeyframe(target, attribute="translateX", time=105, value=-2.0)
        cmds.setKeyframe(target, attribute="translateY", time=120, value=3.0)
        cmds.setKeyframe(other, attribute="translateY", time=120, value=4.0)

        result = clip_io.apply(data, nodes=[target], start_time=100, mode="insert")

        self.assertEqual("insert", result["mode"])
        self.assertEqual(3, result["shifted_keys"])
        self.assertEqual(11.0, result["insert_offset"])
        self.assertEqual(
            [100.0, 110.0, 116.0],
            cmds.keyframe(target, attribute="translateX", query=True, timeChange=True),
        )
        self.assertEqual(
            [131.0],
            cmds.keyframe(target, attribute="translateY", query=True, timeChange=True),
        )
        self.assertEqual(
            [111.0],
            cmds.keyframe(target, attribute="rotateZ", query=True, timeChange=True),
        )
        self.assertEqual(
            [120.0],
            cmds.keyframe(other, attribute="translateY", query=True, timeChange=True),
        )
        cmds.undo()
        self.assertEqual(
            [105.0],
            cmds.keyframe(target, attribute="translateX", query=True, timeChange=True),
        )
        self.assertEqual(
            [120.0],
            cmds.keyframe(target, attribute="translateY", query=True, timeChange=True),
        )
        self.assertEqual(
            [100.0],
            cmds.keyframe(target, attribute="rotateZ", query=True, timeChange=True),
        )

    def test_selected_scope_does_not_apply_other_control(self):
        hand = self._control("source", "hand_ctrl")
        foot = self._control("source", "foot_ctrl")
        cmds.setKeyframe(hand, attribute="translateX", time=1, value=2.0)
        cmds.setKeyframe(foot, attribute="translateX", time=1, value=3.0)
        data = clip_io.capture([hand, foot], start=1, end=1)
        cmds.delete(hand, foot)
        target_hand = self._control("target", "hand_ctrl")
        target_foot = self._control("target", "foot_ctrl")

        clip_io.apply(data, nodes=[target_hand], start_time=5)

        self.assertEqual([5.0], cmds.keyframe(target_hand, attribute="translateX", query=True, timeChange=True))
        self.assertIsNone(cmds.keyframe(target_foot, attribute="translateX", query=True, timeChange=True))

    def test_enum_keys_resolve_by_label_on_reordered_target(self):
        source = self._control("source")
        cmds.addAttr(
            source,
            longName="space",
            attributeType="enum",
            enumName="World=1:Chest=5",
            keyable=True,
        )
        cmds.setKeyframe(source, attribute="space", time=1, value=1)
        cmds.setKeyframe(source, attribute="space", time=2, value=5)
        data = clip_io.capture([source], start=1, end=2)
        cmds.delete(source)
        target = self._control("target")
        cmds.addAttr(
            target,
            longName="space",
            attributeType="enum",
            enumName="Chest=2:World=7",
            keyable=True,
        )

        clip_io.apply(data, nodes=[target], start_time=10)

        self.assertEqual(
            [7.0, 2.0],
            cmds.keyframe(target, attribute="space", query=True, valueChange=True),
        )

    def test_legacy_enum_keys_without_labels_use_numeric_values(self):
        source = self._control("source")
        cmds.addAttr(
            source,
            longName="space",
            attributeType="enum",
            enumName="World=1:Chest=5",
            keyable=True,
        )
        cmds.setKeyframe(source, attribute="space", time=1, value=5)
        data = clip_io.capture([source], start=1, end=1)
        del data["controls"][0]["channels"][0]["keys"][0]["enum_label"]
        cmds.delete(source)
        target = self._control("target")
        cmds.addAttr(
            target,
            longName="space",
            attributeType="enum",
            enumName="World=1:Chest=5",
            keyable=True,
        )

        clip_io.apply(data, nodes=[target], start_time=10)

        self.assertEqual(
            [5.0],
            cmds.keyframe(target, attribute="space", query=True, valueChange=True),
        )

    def test_fixed_weighted_tangents_round_trip(self):
        source = self._control("source")
        plug = source + ".translateX"
        cmds.setKeyframe(plug, time=1, value=0)
        cmds.setKeyframe(plug, time=10, value=5)
        cmds.keyTangent(plug, edit=True, weightedTangents=True)
        cmds.keyTangent(
            plug,
            edit=True,
            time=(1, 1),
            inTangentType="fixed",
            outTangentType="fixed",
            inAngle=12.0,
            outAngle=34.0,
            inWeight=0.5,
            outWeight=0.75,
        )
        data = clip_io.capture([source], start=1, end=10)
        cmds.delete(source)
        target = self._control("target")
        target_plug = target + ".translateX"

        clip_io.apply(data, nodes=[target], start_time=20)

        self.assertEqual([True], cmds.keyTangent(target_plug, query=True, weightedTangents=True))
        self.assertAlmostEqual(
            12.0,
            cmds.keyTangent(target_plug, query=True, time=(20, 20), inAngle=True)[0],
        )
        self.assertAlmostEqual(
            34.0,
            cmds.keyTangent(target_plug, query=True, time=(20, 20), outAngle=True)[0],
        )
        self.assertAlmostEqual(
            0.5,
            cmds.keyTangent(target_plug, query=True, time=(20, 20), inWeight=True)[0],
        )
        self.assertAlmostEqual(
            0.75,
            cmds.keyTangent(target_plug, query=True, time=(20, 20), outWeight=True)[0],
        )

    def test_time_unit_mismatch_is_reported_without_retiming(self):
        original = cmds.currentUnit(query=True, time=True)
        try:
            cmds.currentUnit(time="film")
            source, data = self._source_clip()
            cmds.delete(source)
            target = self._control("target")
            cmds.currentUnit(time="ntsc")

            result = clip_io.apply(data, nodes=[target], start_time=100)

            self.assertTrue(result["time_unit_mismatch"])
            self.assertEqual("film", result["source_time_unit"])
            self.assertEqual("ntsc", result["scene_time_unit"])
            self.assertEqual(
                [100.0, 110.0],
                cmds.keyframe(target, attribute="translateX", query=True, timeChange=True),
            )
        finally:
            cmds.currentUnit(time=original)

    def test_driven_channel_is_skipped(self):
        source, data = self._source_clip()
        cmds.delete(source)
        target = self._control("target")
        driver = cmds.createNode("multiplyDivide")
        cmds.connectAttr(driver + ".outputX", target + ".translateX")

        result = clip_io.apply(data, start_time=1)

        self.assertEqual(0, result["applied_channels"])
        self.assertEqual("driven", result["skipped"][0]["reason"])

    def test_insert_does_not_shift_when_all_clip_channels_are_driven(self):
        source, data = self._source_clip()
        cmds.delete(source)
        target = self._control("target")
        cmds.setKeyframe(target, attribute="translateY", time=20, value=2.0)
        driver = cmds.createNode("multiplyDivide")
        cmds.connectAttr(driver + ".outputX", target + ".translateX")

        result = clip_io.apply(data, nodes=[target], start_time=10, mode="insert")

        self.assertEqual(0, result["shifted_keys"])
        self.assertEqual(
            [20.0],
            cmds.keyframe(target, attribute="translateY", query=True, timeChange=True),
        )

    def test_invalid_key_order_fails_before_edit(self):
        source, data = self._source_clip()
        target = self._control("target")
        invalid = copy.deepcopy(data)
        invalid["controls"][0]["channels"][0]["keys"][1]["time"] = 0.0

        with self.assertRaises(ValueError):
            clip_io.apply(invalid, nodes=[target], start_time=1)

        self.assertIsNone(cmds.keyframe(target, attribute="translateX", query=True, timeChange=True))

    def test_empty_portable_address_is_rejected(self):
        """prefixだけのClip addressをtarget missingとして扱わない。"""
        _source, data = self._source_clip()
        invalid = copy.deepcopy(data)
        invalid["controls"][0]["address"] = "id:"

        with self.assertRaises(ValueError):
            clip_io.apply(invalid, start_time=1)

    def test_invalid_mode_fails_before_edit(self):
        source, data = self._source_clip()
        target = self._control("target")

        with self.assertRaises(ValueError):
            clip_io.apply(data, nodes=[target], start_time=1, mode="append")

        self.assertIsNone(cmds.keyframe(target, attribute="translateX", query=True, timeChange=True))

    def test_non_boolean_legacy_replace_fails_before_edit(self):
        """曖昧なlegacy replace値で既存keyを削除しない。"""
        _source, data = self._source_clip()
        target = self._control("target")
        cmds.setKeyframe(target, attribute="translateX", time=1, value=3.0)

        with self.assertRaises(ValueError):
            clip_io.apply(data, nodes=[target], start_time=1, replace="no")

        self.assertEqual([1.0], cmds.keyframe(target, attribute="translateX", query=True, timeChange=True))

    def test_save_and_read_round_trip(self):
        source, _data = self._source_clip()
        path = self.get_temp_filename("clip.json")

        clip_io.save([source], path, start=10, end=20)
        data = clip_io.read(path)

        self.assertEqual(clip_io.FORMAT, data["format"])
        self.assertEqual(10.0, data["duration"])

    def test_temporary_clip_round_trip_uses_validated_engine(self):
        source, _data = self._source_clip()
        path = self.get_temp_filename("temporary_clip.json")
        clip_io.save_temp([source], file_path=path, start=10, end=20)
        cmds.delete(source)
        target = self._control("target")
        cmds.currentTime(100)

        result = clip_io.load_temp(
            nodes=[target],
            file_path=path,
            mode="place",
        )

        self.assertEqual(2, result["applied_keys"])
        self.assertEqual(
            [100.0, 110.0],
            cmds.keyframe(target, attribute="translateX", query=True, timeChange=True),
        )

    def test_load_settings_round_trip_and_invalid_mode_falls_back(self):
        self.assertEqual(("replace", False), clip_io.get_load_settings())
        self.assertEqual(("insert", True), clip_io.set_load_settings("insert", True))
        self.assertEqual(("insert", True), clip_io.get_load_settings())

        cmds.optionVar(stringValue=(clip_io.MODE_OPTION, "append"))

        self.assertEqual(("replace", True), clip_io.get_load_settings())

    def test_anchor_settings_round_trip(self):
        self.assertEqual((True, True), clip_io.get_anchor_settings())
        self.assertEqual((False, True), clip_io.set_anchor_settings(False, True))
        self.assertEqual((False, True), clip_io.get_anchor_settings())

    def test_load_options_window_builds(self):
        self.assertEqual("ywtaClipLoadOptionsWindow", clip_io.show_load_options())
