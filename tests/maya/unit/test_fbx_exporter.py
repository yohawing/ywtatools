"""原子的 FBX Exporter の Maya 統合テスト。"""

from unittest import mock
import os

import maya.cmds as cmds
import maya.mel as mel

from ywta.io import fbx_exporter
from ywta.test import TestCase


class FbxExporterTests(TestCase):
    """実 FBX plugin 出力と scene state 復元を検証する。"""

    def test_export_selected_writes_fbx_and_restores_state(self):
        cube = cmds.polyCube(name="asset")[0]
        sentinel = cmds.spaceLocator(name="selection_sentinel")[0]
        cmds.select(sentinel, replace=True)
        fbx_exporter._ensure_fbx_plugin()
        mel.eval("FBXExportCameras -v true;")
        path = self.get_temp_filename("asset.fbx")

        result = fbx_exporter.export_selected([cube], path)

        self.assertEqual(os.path.abspath(path), result)
        self.assertGreater(os.path.getsize(path), 0)
        self.assertEqual([sentinel], cmds.ls(selection=True))
        self.assertTrue(mel.eval("FBXExportCameras -q;"))

    def test_export_animation_does_not_rename_skeleton(self):
        cmds.select(clear=True)
        root = cmds.joint(name="root_jnt")
        child = cmds.joint(name="child_jnt", position=(1.0, 0.0, 0.0))
        cmds.setKeyframe(root, attribute="rotateY", time=1, value=0.0)
        cmds.setKeyframe(root, attribute="rotateY", time=10, value=45.0)
        path = self.get_temp_filename("animation.fbx")
        before = cmds.ls(type="joint", long=True)

        result = fbx_exporter.export_animation(root, path, start=1, end=10)

        self.assertEqual(os.path.abspath(path), result)
        self.assertGreater(os.path.getsize(path), 0)
        self.assertEqual(before, cmds.ls(type="joint", long=True))
        self.assertTrue(cmds.objExists(child))

        cmds.file(new=True, force=True)
        mel.eval('FBXImport -f "{}";'.format(path.replace("\\", "/")))
        self.assertTrue(cmds.objExists("root_jnt"))
        self.assertTrue(cmds.objExists("child_jnt"))
        self.assertGreater(
            len(cmds.keyframe("root_jnt", attribute="rotateY", query=True) or []),
            0,
        )

    def test_export_selected_round_trips_skin_cluster(self):
        mesh = cmds.polyCube(name="skinned_asset")[0]
        cmds.select(clear=True)
        root = cmds.joint(name="root_jnt")
        child = cmds.joint(name="child_jnt", position=(1.0, 0.0, 0.0))
        cmds.skinCluster(root, child, mesh, toSelectedBones=True)
        path = self.get_temp_filename("skinned.fbx")

        fbx_exporter.export_selected([mesh, root], path)
        cmds.file(new=True, force=True)
        mel.eval('FBXImport -f "{}";'.format(path.replace("\\", "/")))

        self.assertTrue(cmds.objExists("root_jnt"))
        self.assertTrue(cmds.objExists("child_jnt"))
        clusters = cmds.ls(cmds.listHistory("skinned_asset"), type="skinCluster")
        self.assertEqual(1, len(clusters))

    def test_failed_export_preserves_existing_target_and_selection(self):
        cube = cmds.polyCube(name="asset")[0]
        sentinel = cmds.spaceLocator(name="selection_sentinel")[0]
        cmds.select(sentinel, replace=True)
        path = self.get_temp_filename("existing.fbx")
        with open(path, "wb") as handle:
            handle.write(b"existing")
        original_eval = fbx_exporter.mel.eval

        def fail_export(command):
            if command.startswith("FBXExport -f"):
                raise RuntimeError("expected failure")
            return original_eval(command)

        with mock.patch.object(fbx_exporter.mel, "eval", side_effect=fail_export):
            with self.assertRaises(RuntimeError):
                fbx_exporter.export_selected([cube], path)

        with open(path, "rb") as handle:
            self.assertEqual(b"existing", handle.read())
        self.assertEqual([sentinel], cmds.ls(selection=True))

    def test_invalid_animation_range_fails_before_file_write(self):
        cmds.select(clear=True)
        root = cmds.joint(name="root_jnt")
        path = self.get_temp_filename("invalid.fbx")

        with self.assertRaises(ValueError):
            fbx_exporter.export_animation(root, path, start=10, end=1)

        self.assertFalse(os.path.exists(path))

    def test_missing_explicit_node_rejects_partial_export(self):
        """明示nodeの一部欠落を黙って無視しない。"""
        cube = cmds.polyCube(name="asset")[0]
        sentinel = cmds.spaceLocator(name="selection_sentinel")[0]
        cmds.select(sentinel, replace=True)
        path = self.get_temp_filename("partial.fbx")

        with self.assertRaises(ValueError):
            fbx_exporter.export_selected([cube, "missing_asset"], path)

        self.assertFalse(os.path.exists(path))
        self.assertEqual([sentinel], cmds.ls(selection=True))
