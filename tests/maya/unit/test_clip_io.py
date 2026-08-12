"""Animation Clip IO の Maya 単体テスト。"""

import copy

import maya.cmds as cmds

from ywta.anim import clip_io
from ywta.test import TestCase


class ClipIoTests(TestCase):
    """namespace 可搬 clip の保存・適用 contract を検証する。"""

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

    def test_driven_channel_is_skipped(self):
        source, data = self._source_clip()
        cmds.delete(source)
        target = self._control("target")
        driver = cmds.createNode("multiplyDivide")
        cmds.connectAttr(driver + ".outputX", target + ".translateX")

        result = clip_io.apply(data, start_time=1)

        self.assertEqual(0, result["applied_channels"])
        self.assertEqual("driven", result["skipped"][0]["reason"])

    def test_invalid_key_order_fails_before_edit(self):
        source, data = self._source_clip()
        target = self._control("target")
        invalid = copy.deepcopy(data)
        invalid["controls"][0]["channels"][0]["keys"][1]["time"] = 0.0

        with self.assertRaises(ValueError):
            clip_io.apply(invalid, nodes=[target], start_time=1)

        self.assertIsNone(cmds.keyframe(target, attribute="translateX", query=True, timeChange=True))

    def test_save_and_read_round_trip(self):
        source, _data = self._source_clip()
        path = self.get_temp_filename("clip.json")

        clip_io.save([source], path, start=10, end=20)
        data = clip_io.read(path)

        self.assertEqual(clip_io.FORMAT, data["format"])
        self.assertEqual(10.0, data["duration"])
