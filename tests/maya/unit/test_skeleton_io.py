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

    def test_save_and_read_round_trip(self):
        root, _child = self._skeleton()
        path = self.get_temp_filename("skeleton.skeleton.json")

        skeleton_io.save(root, path)
        data = skeleton_io.read(path)

        self.assertEqual(skeleton_io.FORMAT, data["format"])
        self.assertEqual(["root_jnt", "spine_jnt"], [joint["name"] for joint in data["joints"]])
