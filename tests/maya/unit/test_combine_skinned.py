"""Skinned mesh結合のMaya単体テスト。"""

import maya.api.OpenMaya as om
import maya.api.OpenMayaAnim as oma
import maya.cmds as cmds

from ywta.deform import combine_skinned
from ywta.deform import skin_io
from ywta.test import TestCase


class CombineSkinnedTests(TestCase):
    """元mesh非破壊、正確なweight mapping、Undoを検証する。"""

    def _source(self, name, offset, influences, weights):
        """異なる位置とウェイトを持つplaneを作成する。"""
        mesh = cmds.polyPlane(name=name, width=1.0, height=1.0, subdivisionsX=1, subdivisionsY=1)[0]
        cmds.move(offset, 0.0, 0.0, mesh)
        cluster = cmds.skinCluster(influences, mesh, toSelectedBones=True, normalizeWeights=1)[0]
        for vertex_index, row in enumerate(weights):
            cmds.skinPercent(
                cluster,
                "{}.vtx[{}]".format(mesh, vertex_index),
                transformValue=list(zip(influences, row)),
            )
        return mesh

    @staticmethod
    def _dense_weights(mesh):
        """meshのweightとinfluence leaf名を返す。"""
        shape = skin_io._mesh_shape(mesh)
        cluster = skin_io._skin_cluster(shape)
        fn_skin = oma.MFnSkinCluster(skin_io._depend_node(cluster))
        influences = [path.fullPathName().rsplit("|", 1)[-1] for path in fn_skin.influenceObjects()]
        count = om.MFnMesh(skin_io._dag_path(shape)).numVertices
        weights, influence_count = fn_skin.getWeights(skin_io._dag_path(shape), skin_io._vertex_component(count))
        rows = [list(weights[index * influence_count : (index + 1) * influence_count]) for index in range(count)]
        return influences, rows

    def setUp(self):
        cmds.select(clear=True)
        self.left_joint = cmds.joint(name="left_jnt", position=(-1.0, 0.0, 0.0))
        cmds.select(clear=True)
        self.right_joint = cmds.joint(name="right_jnt", position=(1.0, 0.0, 0.0))
        self.left = self._source(
            "left_mesh",
            -2.0,
            [self.left_joint, self.right_joint],
            [(1.0, 0.0), (0.75, 0.25), (0.5, 0.5), (0.25, 0.75)],
        )
        self.right = self._source(
            "right_mesh",
            2.0,
            [self.right_joint, self.left_joint],
            [(1.0, 0.0), (0.6, 0.4), (0.2, 0.8), (0.0, 1.0)],
        )

    def test_combines_exact_weights_without_changing_sources(self):
        left_uuid = cmds.ls(self.left, uuid=True)[0]
        right_uuid = cmds.ls(self.right, uuid=True)[0]

        result = combine_skinned.combine([self.left, self.right], name="body_mesh")

        self.assertEqual(8, result["vertex_count"])
        self.assertEqual(left_uuid, cmds.ls(self.left, uuid=True)[0])
        self.assertEqual(right_uuid, cmds.ls(self.right, uuid=True)[0])
        influences, rows = self._dense_weights(result["mesh"])
        expected = []
        for source in (self.left, self.right):
            source_influences, source_rows = self._dense_weights(source)
            for row in source_rows:
                by_name = dict(zip(source_influences, row))
                expected.append([by_name.get(influence, 0.0) for influence in influences])
        for actual_row, expected_row in zip(rows, expected):
            for actual, expected_value in zip(actual_row, expected_row):
                self.assertAlmostEqual(expected_value, actual)

    def test_combine_is_single_undoable_action(self):
        cmds.select(self.left, self.right, replace=True)
        result = combine_skinned.combine([self.left, self.right], name="body_mesh")
        combined_uuid = cmds.ls(result["mesh"], uuid=True)[0]

        self.assertEqual(["body_mesh"], cmds.ls(selection=True))

        cmds.undo()

        self.assertFalse(cmds.ls(combined_uuid, uuid=True))
        self.assertTrue(cmds.objExists(self.left))
        self.assertTrue(cmds.objExists(self.right))
        self.assertEqual({self.left, self.right}, set(cmds.ls(selection=True)))

    def test_unskinned_source_fails_before_edit(self):
        plain = cmds.polyCube(name="plain_mesh")[0]

        with self.assertRaises(ValueError):
            combine_skinned.combine([self.left, plain])

        self.assertTrue(cmds.objExists(self.left))
        self.assertTrue(cmds.objExists(plain))
        self.assertFalse(cmds.objExists("combined_skinned_mesh"))

    def test_output_name_collision_fails_before_edit(self):
        occupied = cmds.createNode("transform", name="body_mesh")
        before = set(cmds.ls(long=True))

        with self.assertRaises(ValueError):
            combine_skinned.combine([self.left, self.right], name="body_mesh")

        self.assertEqual(before, set(cmds.ls(long=True)))
        self.assertTrue(cmds.objExists(occupied))
