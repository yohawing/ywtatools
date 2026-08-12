"""Vertex Weight Clipboard / Average の Maya 単体テスト。"""

import maya.cmds as cmds

from ywta.deform import skin_weights
from ywta.test import TestCase


class SkinWeightsTests(TestCase):
    """選択頂点ウェイト編集の contract を検証する。"""

    def setUp(self):
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

        skin_weights.paste_vertex_weights([self.vertices[3]], data=data)

        self.assertEqual(self._weights(self.vertices[0]), self._weights(self.vertices[3]))
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
