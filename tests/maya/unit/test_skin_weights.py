"""Vertex Weight Clipboard / Average の Maya 単体テスト。"""

import json

import maya.cmds as cmds

from ywta.deform import skin_weights
from ywta.test import TestCase


class SkinWeightsTests(TestCase):
    """選択頂点ウェイト編集の contract を検証する。"""

    def setUp(self):
        skin_weights._CLIPBOARD = None
        self.mesh = cmds.polyPlane(name="cloth", subdivisionsX=1, subdivisionsY=1)[0]
        cmds.select(clear=True)
        self.root = cmds.joint(name="root_jnt", position=(-1.0, 0.0, 0.0))
        cmds.select(clear=True)
        self.tip = cmds.joint(name="tip_jnt", position=(1.0, 0.0, 0.0))
        self.cluster = cmds.skinCluster(self.root, self.tip, self.mesh, toSelectedBones=True, normalizeWeights=1)[0]
        self.vertices = cmds.ls(self.mesh + ".vtx[*]", flatten=True)
        for index, vertex in enumerate(self.vertices):
            root_weight = 1.0 if index < 2 else 0.0
            cmds.skinPercent(
                self.cluster,
                vertex,
                transformValue=(
                    (self.root, root_weight),
                    (self.tip, 1.0 - root_weight),
                ),
            )

    def _weights(self, vertex):
        return cmds.skinPercent(self.cluster, vertex, query=True, value=True)

    def test_copy_and_paste_vertex_weights_with_single_undo(self):
        data = skin_weights.capture_vertex_weights(self.vertices[0])
        before = self._weights(self.vertices[3])
        cmds.select(self.vertices[3], replace=True)

        skin_weights.paste_vertex_weights(data=data)

        self.assertEqual(self._weights(self.vertices[0]), self._weights(self.vertices[3]))
        self.assertEqual(
            cmds.ls(self.vertices[3], long=True, flatten=True),
            cmds.ls(selection=True, long=True, flatten=True),
        )
        cmds.undo()
        self.assertEqual(before, self._weights(self.vertices[3]))

    def test_average_selected_vertex_weights(self):
        selected = [self.vertices[0], self.vertices[3]]
        before = [self._weights(vertex) for vertex in selected]

        skin_weights.average_vertex_weights(selected)

        for vertex in selected:
            values = self._weights(vertex)
            self.assertAlmostEqual(0.5, values[0])
            self.assertAlmostEqual(0.5, values[1])
        cmds.undo()
        self.assertEqual(before, [self._weights(vertex) for vertex in selected])

    def test_copy_average_can_paste_without_changing_sources(self):
        """複数頂点平均をclipboard化し、元頂点を変えず別頂点へ貼る。"""
        path = self.get_temp_filename("average_clipboard.json")
        sources = [self.vertices[0], self.vertices[3]]
        before = [self._weights(vertex) for vertex in sources]

        data = skin_weights.copy_average_vertex_weights(sources, file_path=path)
        skin_weights.paste_vertex_weights([self.vertices[1]], clipboard_file=path)

        self.assertEqual(before, [self._weights(vertex) for vertex in sources])
        self.assertAlmostEqual(0.5, data["weights"][0])
        self.assertAlmostEqual(0.5, data["weights"][1])
        self.assertEqual(data["weights"], self._weights(self.vertices[1]))

    def test_paste_zeros_existing_extra_influence(self):
        data = skin_weights.capture_vertex_weights(self.vertices[0])
        cmds.select(clear=True)
        extra = cmds.joint(name="extra_jnt", position=(0.0, 1.0, 0.0))
        cmds.skinCluster(self.cluster, edit=True, addInfluence=extra, weight=1.0)

        skin_weights.paste_vertex_weights([self.vertices[3]], data=data)

        self.assertAlmostEqual(
            0.0,
            cmds.skinPercent(self.cluster, self.vertices[3], query=True, transform=extra),
        )

    def test_vertices_from_multiple_meshes_are_rejected(self):
        other = cmds.polyPlane(name="other")[0]

        with self.assertRaises(ValueError):
            skin_weights.average_vertex_weights([self.vertices[0], other + ".vtx[0]"])

    def test_copy_requires_exactly_one_vertex(self):
        cmds.select(self.vertices[:2], replace=True)

        with self.assertRaises(ValueError):
            skin_weights.copy_selected_vertex_weights()

    def test_clipboard_persists_across_process_memory_reset(self):
        path = self.get_temp_filename("weight_clipboard.json")
        cmds.select(self.vertices[0], replace=True)
        expected = skin_weights.copy_selected_vertex_weights(file_path=path)
        skin_weights._CLIPBOARD = None

        skin_weights.paste_vertex_weights(
            [self.vertices[3]],
            clipboard_file=path,
        )

        self.assertEqual(expected["weights"], self._weights(self.vertices[3]))

    def test_invalid_persistent_clipboard_fails_before_edit(self):
        path = self.get_temp_filename("invalid_weight_clipboard.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"format": "other", "version": 1, "data": {}}, handle)
        before = self._weights(self.vertices[3])

        with self.assertRaises(ValueError):
            skin_weights.paste_vertex_weights(
                [self.vertices[3]],
                clipboard_file=path,
            )

        self.assertEqual(before, self._weights(self.vertices[3]))

    def test_missing_explicit_clipboard_does_not_use_stale_memory(self):
        """明示した欠落ファイルをprocess内clipboardで代用しない。"""
        skin_weights._CLIPBOARD = skin_weights.capture_vertex_weights(self.vertices[0])
        before = self._weights(self.vertices[3])

        with self.assertRaises(ValueError):
            skin_weights.paste_vertex_weights(
                [self.vertices[3]],
                clipboard_file=self.get_temp_filename("missing_clipboard.json"),
            )

        self.assertEqual(before, self._weights(self.vertices[3]))

    def test_disk_clipboard_wins_over_stale_process_cache(self):
        path = self.get_temp_filename("shared_weight_clipboard.json")
        stale = skin_weights.capture_vertex_weights(self.vertices[0])
        current = skin_weights.capture_vertex_weights(self.vertices[3])
        skin_weights._CLIPBOARD = stale
        skin_weights.write_clipboard(current, file_path=path)

        skin_weights.paste_vertex_weights(
            [self.vertices[1]],
            clipboard_file=path,
        )

        self.assertEqual(current["weights"], self._weights(self.vertices[1]))
