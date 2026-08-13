"""YZスキンウェイトミラーのMaya単体テスト。"""

import maya.cmds as cmds

from ywta.deform import skin_mirror
from ywta.test import TestCase


class SkinMirrorTests(TestCase):
    """方向、Undo、事前検証を確認する。"""

    @staticmethod
    def _scene():
        """左右対称meshとinfluenceを作成する。"""
        mesh = cmds.polyPlane(name="body", width=2, height=1, subdivisionsX=2, subdivisionsY=1)[0]
        cmds.select(clear=True)
        left = cmds.joint(name="L_joint", position=(1, 0, 0))
        cmds.select(clear=True)
        right = cmds.joint(name="R_joint", position=(-1, 0, 0))
        cluster = cmds.skinCluster([left, right], mesh, toSelectedBones=True, normalizeWeights=1)[0]
        for index in range(cmds.polyEvaluate(mesh, vertex=True)):
            cmds.skinPercent(cluster, "{}.vtx[{}]".format(mesh, index), transformValue=[(left, 1.0), (right, 0.0)])
        return mesh, cluster, left, right

    @staticmethod
    def _weights(cluster, mesh, influence, side):
        """指定X側の頂点ウェイトを返す。"""
        values = []
        for index in range(cmds.polyEvaluate(mesh, vertex=True)):
            x = cmds.pointPosition("{}.vtx[{}]".format(mesh, index), world=True)[0]
            if (side == "positive" and x > 1.0e-6) or (side == "negative" and x < -1.0e-6):
                values.append(cmds.skinPercent(cluster, "{}.vtx[{}]".format(mesh, index), query=True, transform=influence))
        return values

    def test_positive_to_negative_mirror_is_undoable(self):
        """+X側の左jointウェイトを-X側の右jointへミラーする。"""
        mesh, cluster, left, right = self._scene()
        sentinel = cmds.spaceLocator(name="selection_sentinel")[0]
        cmds.select(sentinel, replace=True)

        result = skin_mirror.mirror_skin_weights(
            mesh,
            mirror_inverse=False,
            influence_associations=("closestJoint",),
        )

        self.assertEqual("positive_to_negative", result["direction"])
        self.assertEqual([sentinel], cmds.ls(selection=True))
        self.assertTrue(all(value > 0.999 for value in self._weights(cluster, mesh, left, "positive")))
        self.assertTrue(all(value > 0.999 for value in self._weights(cluster, mesh, right, "negative")))

        cmds.undo()
        self.assertTrue(all(value > 0.999 for value in self._weights(cluster, mesh, left, "negative")))
        cmds.redo()
        self.assertTrue(all(value > 0.999 for value in self._weights(cluster, mesh, right, "negative")))

    def test_locked_influence_rejects_before_edit(self):
        """locked influenceがある場合はウェイトを変更しない。"""
        mesh, cluster, left, right = self._scene()
        cmds.setAttr(right + ".lockInfluenceWeights", True)

        with self.assertRaises(ValueError):
            skin_mirror.mirror_skin_weights(mesh)

        self.assertTrue(all(value > 0.999 for value in self._weights(cluster, mesh, left, "negative")))

    def test_negative_to_positive_mirror_uses_inverse_direction(self):
        """mirrorInverseで-X側の右jointウェイトを+X側へ反転する。"""
        mesh, cluster, left, right = self._scene()
        for index in range(cmds.polyEvaluate(mesh, vertex=True)):
            cmds.skinPercent(cluster, "{}.vtx[{}]".format(mesh, index), transformValue=[(left, 0.0), (right, 1.0)])

        result = skin_mirror.mirror_skin_weights(
            mesh,
            mirror_inverse=True,
            influence_associations=("closestJoint",),
        )

        self.assertEqual("negative_to_positive", result["direction"])
        self.assertTrue(all(value > 0.999 for value in self._weights(cluster, mesh, left, "positive")))

    def test_selected_entry_requires_exactly_one_skinned_mesh(self):
        """複数mesh選択を暗黙に先頭だけへ適用しない。"""
        first, _cluster, _left, _right = self._scene()
        second = cmds.polyCube(name="other_mesh")[0]
        cmds.select(first, second, replace=True)

        with self.assertRaises(ValueError):
            skin_mirror.mirror_selected_positive_to_negative()
