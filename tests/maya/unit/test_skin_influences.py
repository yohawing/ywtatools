"""Skin Influence ToolsのMaya単体テスト。"""

import maya.cmds as cmds

from ywta.deform import skin_influences
from ywta.test import TestCase


class SkinInfluenceTests(TestCase):
    """weight保持、事前拒否、単一Undoを検証する。"""

    def setUp(self):
        self.mesh = cmds.polyPlane(name="cloth")[0]
        cmds.select(clear=True)
        self.root = cmds.joint(name="root_jnt")
        cmds.select(clear=True)
        self.extra = cmds.joint(name="extra_jnt", position=(1.0, 0.0, 0.0))
        self.cluster = cmds.skinCluster(self.root, self.mesh, toSelectedBones=True)[0]

    def _influences(self):
        return cmds.skinCluster(self.cluster, query=True, influence=True) or []

    def test_add_preserves_weights_and_is_one_undo(self):
        vertex = self.mesh + ".vtx[0]"
        before = cmds.skinPercent(self.cluster, vertex, query=True, value=True)

        result = skin_influences.add_influences([self.mesh], [self.extra])

        self.assertEqual(1, len(result["added"]))
        self.assertIn(self.extra, self._influences())
        self.assertEqual(before + [0.0], cmds.skinPercent(self.cluster, vertex, query=True, value=True))
        cmds.undo()
        self.assertNotIn(self.extra, self._influences())

    def test_remove_unused_is_one_undo(self):
        skin_influences.add_influences([self.mesh], [self.extra])
        cmds.flushUndo()

        result = skin_influences.remove_influences([self.mesh], [self.extra])

        self.assertEqual(1, len(result["removed"]))
        self.assertNotIn(self.extra, self._influences())
        cmds.undo()
        self.assertIn(self.extra, self._influences())

    def test_remove_used_fails_before_edit(self):
        skin_influences.add_influences([self.mesh], [self.extra])
        cmds.skinPercent(
            self.cluster,
            self.mesh + ".vtx[0]",
            transformValue=((self.root, 0.5), (self.extra, 0.5)),
        )
        before = self._influences()

        with self.assertRaises(ValueError):
            skin_influences.remove_influences([self.mesh], [self.extra])

        self.assertEqual(before, self._influences())

    def test_multi_mesh_remove_preflights_every_cluster(self):
        skin_influences.add_influences([self.mesh], [self.extra])
        second_mesh = cmds.polyPlane(name="cape")[0]
        second_cluster = cmds.skinCluster(
            self.root,
            self.extra,
            second_mesh,
            toSelectedBones=True,
        )[0]
        cmds.skinPercent(
            second_cluster,
            second_mesh + ".vtx[0]",
            transformValue=((self.root, 0.5), (self.extra, 0.5)),
        )

        with self.assertRaises(ValueError):
            skin_influences.remove_influences(
                [self.mesh, second_mesh],
                [self.extra],
            )

        self.assertIn(self.extra, self._influences())

    def test_remove_locked_fails_before_edit(self):
        skin_influences.add_influences([self.mesh], [self.extra])
        cmds.setAttr(self.extra + ".lockInfluenceWeights", True)

        with self.assertRaises(ValueError):
            skin_influences.remove_influences([self.mesh], [self.extra])

        self.assertIn(self.extra, self._influences())

    def test_mixed_selection_drives_menu_actions(self):
        cmds.select(self.mesh, self.extra, replace=True)
        before = cmds.ls(selection=True, long=True)

        skin_influences.add_selected_influences()

        self.assertIn(self.extra, self._influences())
        self.assertEqual(before, cmds.ls(selection=True, long=True))

        skin_influences.remove_selected_influences()

        self.assertNotIn(self.extra, self._influences())
        self.assertEqual(before, cmds.ls(selection=True, long=True))
