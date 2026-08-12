"""Versioned Skeleton IO の Maya 単体テスト。"""

import copy

import maya.cmds as cmds

from ywta.rig import skeleton_io
from ywta.test import TestCase


class SkeletonIoTests(TestCase):
    """安全な hierarchy round-trip contract を検証する。"""

    def _skeleton(self, namespace=""):
        if namespace and not cmds.namespace(exists=namespace):
            cmds.namespace(add=namespace)
        prefix = namespace + ":" if namespace else ""
        cmds.select(clear=True)
        root = cmds.joint(name=prefix + "root_jnt", position=(1.0, 2.0, 3.0))
        child = cmds.joint(name=prefix + "spine_jnt", position=(1.0, 5.0, 3.0))
        cmds.setAttr(child + ".jointOrient", 10.0, 20.0, 30.0)
        cmds.setAttr(child + ".rotateOrder", 2)
        cmds.setAttr(child + ".radius", 1.75)
        return root, child

    def test_capture_and_create_round_trip(self):
        root, child = self._skeleton()
        expected_translate = cmds.getAttr(child + ".translate")[0]
        expected_orient = cmds.getAttr(child + ".jointOrient")[0]
        data = skeleton_io.capture(root)
        cmds.delete(root)

        created = skeleton_io.create(data)

        self.assertEqual(2, len(created))
        self.assertEqual("|root_jnt|spine_jnt", created[1])
        self.assertEqual(expected_translate, cmds.getAttr(created[1] + ".translate")[0])
        self.assertEqual(expected_orient, cmds.getAttr(created[1] + ".jointOrient")[0])
        self.assertEqual(2, cmds.getAttr(created[1] + ".rotateOrder"))
        self.assertAlmostEqual(1.75, cmds.getAttr(created[1] + ".radius"))

    def test_create_in_real_namespace(self):
        root, _child = self._skeleton("source")
        data = skeleton_io.capture(root)
        cmds.delete(root)

        created = skeleton_io.create(data, namespace="target:rig")

        self.assertTrue(cmds.namespace(exists="target:rig"))
        self.assertEqual("target:rig:root_jnt", created[0].rsplit("|", 1)[-1])
        self.assertEqual("target:rig:spine_jnt", created[1].rsplit("|", 1)[-1])

    def test_joint_labels_limits_and_channel_states_round_trip(self):
        root, child = self._skeleton()
        cmds.setAttr(child + ".side", 1)
        cmds.setAttr(child + ".type", 18)
        cmds.setAttr(child + ".otherType", "elbow", type="string")
        cmds.setAttr(child + ".drawLabel", True)
        cmds.setAttr(child + ".minRotLimit", -10.0, -20.0, -30.0)
        cmds.setAttr(child + ".maxRotLimit", 10.0, 20.0, 30.0)
        cmds.setAttr(child + ".minRotLimitEnable", True, False, True)
        cmds.setAttr(child + ".maxRotLimitEnable", False, True, True)
        cmds.setAttr(child + ".rotateX", keyable=False, channelBox=False)
        cmds.setAttr(child + ".rotateX", lock=True)
        data = skeleton_io.capture(root)
        cmds.delete(root)

        created = skeleton_io.create(data)
        rebuilt = created[1]

        self.assertEqual(1, cmds.getAttr(rebuilt + ".side"))
        self.assertEqual(18, cmds.getAttr(rebuilt + ".type"))
        self.assertEqual("elbow", cmds.getAttr(rebuilt + ".otherType"))
        self.assertTrue(cmds.getAttr(rebuilt + ".drawLabel"))
        for expected, actual in zip(
            (-10.0, -20.0, -30.0),
            cmds.getAttr(rebuilt + ".minRotLimit")[0],
        ):
            self.assertAlmostEqual(expected, actual)
        for expected, actual in zip(
            (10.0, 20.0, 30.0),
            cmds.getAttr(rebuilt + ".maxRotLimit")[0],
        ):
            self.assertAlmostEqual(expected, actual)
        self.assertEqual((True, False, True), cmds.getAttr(rebuilt + ".minRotLimitEnable")[0])
        self.assertEqual((False, True, True), cmds.getAttr(rebuilt + ".maxRotLimitEnable")[0])
        self.assertTrue(cmds.getAttr(rebuilt + ".rotateX", lock=True))
        self.assertFalse(cmds.getAttr(rebuilt + ".rotateX", keyable=True))

    def test_create_namespace_is_absolute_from_current_namespace(self):
        root, _child = self._skeleton("source")
        data = skeleton_io.capture(root)
        cmds.delete(root)
        cmds.namespace(add="working")
        cmds.namespace(set="working")
        try:
            created = skeleton_io.create(data, namespace="target")
        finally:
            cmds.namespace(set=":")

        self.assertEqual("target:root_jnt", created[0].rsplit("|", 1)[-1])
        self.assertFalse(cmds.namespace(exists="working:target"))

    def test_existing_root_collision_is_rejected_before_edit(self):
        root, _child = self._skeleton()
        data = skeleton_io.capture(root)

        with self.assertRaises(ValueError):
            skeleton_io.create(data)

        self.assertEqual(2, len(cmds.ls(type="joint")))

    def test_invalid_parent_index_is_rejected_before_edit(self):
        root, _child = self._skeleton()
        data = copy.deepcopy(skeleton_io.capture(root))
        cmds.delete(root)
        data["joints"][1]["parent"] = 2

        with self.assertRaises(ValueError):
            skeleton_io.create(data)

        self.assertFalse(cmds.ls(type="joint"))

    def test_version_one_without_channel_states_remains_readable(self):
        root, _child = self._skeleton()
        data = skeleton_io.capture(root)
        for joint in data["joints"]:
            del joint["channels"]
        cmds.delete(root)

        created = skeleton_io.create(data)

        self.assertEqual(2, len(created))

    def test_invalid_channel_state_is_rejected_before_edit(self):
        root, _child = self._skeleton()
        data = skeleton_io.capture(root)
        data["joints"][0]["channels"]["rotateX"]["locked"] = "yes"
        cmds.delete(root)

        with self.assertRaises(ValueError):
            skeleton_io.create(data)

        self.assertFalse(cmds.ls(type="joint"))

    def test_save_and_read_round_trip(self):
        root, _child = self._skeleton()
        path = self.get_temp_filename("skeleton.skeleton.json")

        skeleton_io.save(root, path)
        data = skeleton_io.read(path)

        self.assertEqual(skeleton_io.FORMAT, data["format"])
        self.assertEqual(["root_jnt", "spine_jnt"], [joint["name"] for joint in data["joints"]])
        self.assertEqual(cmds.currentUnit(query=True, linear=True), data["scene"]["linear_unit"])
        self.assertEqual(cmds.currentUnit(query=True, angle=True), data["scene"]["angle_unit"])
        self.assertEqual(cmds.upAxis(query=True, axis=True), data["scene"]["up_axis"])

    def test_temporary_skeleton_round_trip_uses_validated_import(self):
        root, _child = self._skeleton()
        path = self.get_temp_filename("temporary_skeleton.json")
        skeleton_io.save_temp(root, file_path=path)
        cmds.delete(root)

        created = skeleton_io.load_temp(
            file_path=path,
            namespace="temporary",
        )

        self.assertEqual("temporary:root_jnt", created[0].rsplit("|", 1)[-1])
        self.assertEqual("temporary:spine_jnt", created[1].rsplit("|", 1)[-1])

    def test_scene_convention_mismatch_is_rejected_before_edit(self):
        root, _child = self._skeleton()
        data = skeleton_io.capture(root)
        cmds.delete(root)
        data["scene"]["linear_unit"] = "m" if cmds.currentUnit(query=True, linear=True) != "m" else "cm"

        with self.assertRaises(ValueError):
            skeleton_io.create(data)

        self.assertFalse(cmds.ls(type="joint"))

    def test_scene_convention_mismatch_can_be_explicitly_allowed(self):
        root, _child = self._skeleton()
        data = skeleton_io.capture(root)
        cmds.delete(root)
        data["scene"]["linear_unit"] = "m" if cmds.currentUnit(query=True, linear=True) != "m" else "cm"

        created = skeleton_io.create(data, allow_scene_mismatch=True)

        self.assertEqual(2, len(created))

    def test_bake_to_joint_orient_zeros_rotate_and_preserves_world_matrix(self):
        root, child = self._skeleton()
        cmds.setAttr(root + ".rotate", 15.0, -8.0, 22.0)
        cmds.setAttr(child + ".rotate", 9.0, 11.0, -14.0)
        cmds.setAttr(root + ".rotateOrder", 5)
        cmds.setAttr(child + ".rotateOrder", 3)
        expected = {
            joint.rsplit("|", 1)[-1]: cmds.xform(joint, query=True, worldSpace=True, matrix=True)
            for joint in cmds.ls(root, child, long=True)
        }
        data = skeleton_io.capture(root)
        cmds.delete(root)

        created = skeleton_io.create(data, bake_to_joint_orient=True)

        for joint in created:
            self.assertEqual((0.0, 0.0, 0.0), cmds.getAttr(joint + ".rotate")[0])
            actual = cmds.xform(joint, query=True, worldSpace=True, matrix=True)
            leaf = joint.rsplit("|", 1)[-1]
            for expected_value, actual_value in zip(expected[leaf], actual):
                self.assertAlmostEqual(expected_value, actual_value)

    def test_import_is_single_undoable_action(self):
        root, _child = self._skeleton()
        data = skeleton_io.capture(root)
        cmds.delete(root)

        created = skeleton_io.create(data)
        root_uuid = cmds.ls(created[0], uuid=True)[0]
        cmds.undo()

        self.assertFalse(cmds.ls(root_uuid, uuid=True))

    def test_zero_joint_scales_preserves_world_translation_and_rotation(self):
        root, child = self._skeleton()
        cmds.setAttr(root + ".scale", 2.0, 0.5, 1.5)
        cmds.setAttr(child + ".scale", 0.75, 1.25, 2.0)
        expected = {
            joint.rsplit("|", 1)[-1]: (
                cmds.xform(joint, query=True, worldSpace=True, translation=True),
                cmds.xform(joint, query=True, worldSpace=True, rotation=True),
            )
            for joint in cmds.ls(root, child, long=True)
        }
        data = skeleton_io.capture(root)
        cmds.delete(root)

        created = skeleton_io.create(data, zero_joint_scales=True)

        for joint in created:
            self.assertEqual((1.0, 1.0, 1.0), cmds.getAttr(joint + ".scale")[0])
            leaf = joint.rsplit("|", 1)[-1]
            actual = (
                cmds.xform(joint, query=True, worldSpace=True, translation=True),
                cmds.xform(joint, query=True, worldSpace=True, rotation=True),
            )
            for expected_values, actual_values in zip(expected[leaf], actual):
                for expected_value, actual_value in zip(expected_values, actual_values):
                    self.assertAlmostEqual(expected_value, actual_value)

    def test_clean_joint_trs_combines_scale_and_rotate_bakes(self):
        root, child = self._skeleton()
        cmds.setAttr(root + ".scale", 2.0, 0.5, 1.5)
        cmds.setAttr(child + ".rotate", 9.0, 11.0, -14.0)
        data = skeleton_io.capture(root)
        cmds.delete(root)

        created = skeleton_io.create(
            data,
            zero_joint_scales=True,
            bake_to_joint_orient=True,
        )

        for joint in created:
            self.assertEqual((1.0, 1.0, 1.0), cmds.getAttr(joint + ".scale")[0])
            self.assertEqual((0.0, 0.0, 0.0), cmds.getAttr(joint + ".rotate")[0])
