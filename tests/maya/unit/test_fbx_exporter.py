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

    def test_skinned_mesh_only_export_includes_influence_root(self):
        """mesh単独選択でもjointとskinClusterをFBXに含める。"""
        mesh = cmds.polyCube(name="mesh_only_asset")[0]
        cmds.select(clear=True)
        root = cmds.joint(name="root_jnt")
        child = cmds.joint(name="child_jnt", position=(1.0, 0.0, 0.0))
        cmds.skinCluster(root, child, mesh, toSelectedBones=True)
        path = self.get_temp_filename("mesh_only_asset.fbx")

        fbx_exporter.export_selected([mesh], path)
        cmds.file(new=True, force=True)
        mel.eval('FBXImport -f "{}";'.format(path.replace("\\", "/")))

        self.assertTrue(cmds.objExists("root_jnt"))
        self.assertTrue(cmds.objExists("child_jnt"))
        clusters = cmds.ls(cmds.listHistory("mesh_only_asset"), type="skinCluster")
        self.assertEqual(1, len(clusters))

    def test_group_export_includes_descendant_skin_root(self):
        """asset group単独選択でも子孫meshのjointをFBXへ含める。"""
        group = cmds.createNode("transform", name="asset_grp")
        mesh = cmds.polyCube(name="grouped_asset")[0]
        cmds.parent(mesh, group)
        cmds.select(clear=True)
        root = cmds.joint(name="root_jnt")
        child = cmds.joint(name="child_jnt", position=(1.0, 0.0, 0.0))
        cmds.skinCluster(root, child, mesh, toSelectedBones=True)
        path = self.get_temp_filename("grouped_asset.fbx")

        fbx_exporter.export_selected(group, path)
        cmds.file(new=True, force=True)
        mel.eval('FBXImport -f "{}";'.format(path.replace("\\", "/")))

        self.assertTrue(cmds.objExists("root_jnt"))
        clusters = cmds.ls(cmds.listHistory("grouped_asset"), type="skinCluster")
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

    def test_animation_range_prefers_highlight_and_falls_back(self):
        """time sliderの選択範囲をinclusive rangeへ変換する。"""
        with (
            mock.patch.object(fbx_exporter.mel, "eval", return_value="timeControl1"),
            mock.patch.object(
                fbx_exporter.cmds,
                "timeControl",
                side_effect=lambda _slider, **kwargs: True if kwargs.get("rangeVisible") else [5.0, 11.0],
            ),
        ):
            self.assertEqual((5.0, 10.0), fbx_exporter.animation_range())

        playback = (
            float(cmds.playbackOptions(query=True, minTime=True)),
            float(cmds.playbackOptions(query=True, maxTime=True)),
        )
        with mock.patch.object(fbx_exporter.mel, "eval", side_effect=RuntimeError("standalone")):
            self.assertEqual(playback, fbx_exporter.animation_range())

    def test_animation_range_accepts_single_frame_and_rejects_malformed_ui_values(self):
        """1frame highlightを保持し、壊れたtimeControl値はplaybackへ戻す。"""
        playback = (
            float(cmds.playbackOptions(query=True, minTime=True)),
            float(cmds.playbackOptions(query=True, maxTime=True)),
        )

        def time_control(_slider, **kwargs):
            return True if kwargs.get("rangeVisible") else [7.0, 8.0]

        with (
            mock.patch.object(fbx_exporter.mel, "eval", return_value="timeControl1"),
            mock.patch.object(fbx_exporter.cmds, "timeControl", side_effect=time_control),
        ):
            self.assertEqual((7.0, 7.0), fbx_exporter.animation_range())

        def malformed_time_control(_slider, **kwargs):
            return True if kwargs.get("rangeVisible") else ["bad", 8.0]

        with (
            mock.patch.object(fbx_exporter.mel, "eval", return_value="timeControl1"),
            mock.patch.object(fbx_exporter.cmds, "timeControl", side_effect=malformed_time_control),
        ):
            self.assertEqual(playback, fbx_exporter.animation_range())

    def test_mid_chain_animation_root_fails_before_file_write(self):
        """joint chainの途中だけを完全なanimationとして出力しない。"""
        cmds.select(clear=True)
        root = cmds.joint(name="root_jnt")
        child = cmds.joint(name="child_jnt", position=(1.0, 0.0, 0.0))
        path = self.get_temp_filename("partial_animation.fbx")
        cmds.select(root, replace=True)

        with self.assertRaises(ValueError):
            fbx_exporter.export_animation(child, path, start=1, end=10)

        self.assertFalse(os.path.exists(path))
        self.assertEqual([root], cmds.ls(selection=True))

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

    def test_ambiguous_influence_name_rejects_before_file_write(self):
        """skin rootを推測して不完全FBXを書かない。"""
        mesh = cmds.polyCube(name="asset")[0]
        path = self.get_temp_filename("ambiguous.fbx")
        original_ls = fbx_exporter.cmds.ls

        def ambiguous_ls(*args, **kwargs):
            if args and args[0] == ["skinCluster1"] and kwargs.get("type") == "skinCluster":
                return ["skinCluster1"]
            if args and args[0] == "joint" and kwargs.get("type") == "joint":
                return ["|first|joint", "|second|joint"]
            return original_ls(*args, **kwargs)

        with (
            mock.patch.object(fbx_exporter.cmds, "listHistory", return_value=["skinCluster1"]),
            mock.patch.object(
                fbx_exporter.cmds,
                "ls",
                side_effect=ambiguous_ls,
            ),
            mock.patch.object(fbx_exporter.cmds, "skinCluster", return_value=["joint"]),
        ):
            with self.assertRaises(ValueError):
                fbx_exporter.export_selected([mesh], path)

        self.assertFalse(os.path.exists(path))
