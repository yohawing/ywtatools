"""局所skin smoothingのMaya単体テスト。"""

import maya.api.OpenMaya as om
import maya.api.OpenMayaAnim as oma
import maya.cmds as cmds

from ywta.deform import skin_io
from ywta.deform import skin_smooth
from ywta.test import TestCase


class SkinSmoothTests(TestCase):
    """隣接平均、lock保護、複数mesh、Undoを検証する。"""

    def setUp(self):
        for option in (skin_smooth.STRENGTH_OPTION, skin_smooth.ITERATIONS_OPTION):
            if cmds.optionVar(exists=option):
                cmds.optionVar(remove=option)
        cmds.select(clear=True)
        self.root = cmds.joint(name="root_jnt", position=(-1.0, 0.0, 0.0))
        cmds.select(clear=True)
        self.tip = cmds.joint(name="tip_jnt", position=(1.0, 0.0, 0.0))

    def _mesh(self, name, offset=0.0):
        mesh = cmds.polyPlane(name=name, subdivisionsX=2, subdivisionsY=1)[0]
        cmds.move(offset, 0.0, 0.0, mesh)
        cluster = cmds.skinCluster(self.root, self.tip, mesh, toSelectedBones=True, normalizeWeights=1)[0]
        count = cmds.polyEvaluate(mesh, vertex=True)
        for index in range(count):
            value = 1.0 if index % 2 == 0 else 0.0
            cmds.skinPercent(
                cluster,
                "{}.vtx[{}]".format(mesh, index),
                transformValue=((self.root, value), (self.tip, 1.0 - value)),
            )
        return mesh, cluster

    @staticmethod
    def _rows(mesh):
        shape = skin_io._mesh_shape(mesh)
        cluster = skin_io._skin_cluster(shape)
        fn_skin = oma.MFnSkinCluster(skin_io._depend_node(cluster))
        count = om.MFnMesh(skin_io._dag_path(shape)).numVertices
        weights, influence_count = fn_skin.getWeights(skin_io._dag_path(shape), skin_io._vertex_component(count))
        return [[float(weights[row * influence_count + column]) for column in range(influence_count)] for row in range(count)]

    @staticmethod
    def _neighbors(mesh, index):
        iterator = om.MItMeshVertex(skin_io._dag_path(skin_io._mesh_shape(mesh)))
        iterator.setIndex(index)
        return list(iterator.getConnectedVertices())

    def test_full_strength_matches_neighbor_average(self):
        mesh, _cluster = self._mesh("cloth")
        before = self._rows(mesh)
        index = 2
        neighbors = self._neighbors(mesh, index)
        expected = [sum(before[neighbor][influence] for neighbor in neighbors) / len(neighbors) for influence in range(2)]

        result = skin_smooth.smooth(["{}.vtx[{}]".format(mesh, index)], strength=1.0)

        after = self._rows(mesh)[index]
        self.assertEqual(1, result["vertices"])
        for actual, expected_value in zip(after, expected):
            self.assertAlmostEqual(expected_value, actual)

    def test_locked_influence_weight_is_preserved(self):
        mesh, _cluster = self._mesh("cloth")
        index = 2
        before = self._rows(mesh)[index]
        cmds.setAttr(self.root + ".lockInfluenceWeights", True)

        skin_smooth.smooth(["{}.vtx[{}]".format(mesh, index)], strength=1.0)

        self.assertAlmostEqual(before[0], self._rows(mesh)[index][0])

    def test_zero_unlocked_neighbor_average_keeps_normalized_target(self):
        mesh, cluster = self._mesh("cloth")
        index = 1
        for neighbor in self._neighbors(mesh, index):
            cmds.skinPercent(
                cluster,
                "{}.vtx[{}]".format(mesh, neighbor),
                transformValue=((self.root, 1.0), (self.tip, 0.0)),
            )
        cmds.setAttr(self.root + ".lockInfluenceWeights", True)
        before = self._rows(mesh)[index]

        skin_smooth.smooth(["{}.vtx[{}]".format(mesh, index)], strength=1.0)

        after = self._rows(mesh)[index]
        self.assertAlmostEqual(before[0], after[0])
        self.assertAlmostEqual(1.0, sum(after))

    def test_multiple_meshes_are_one_undoable_action(self):
        first, _first_cluster = self._mesh("first", -2.0)
        second, _second_cluster = self._mesh("second", 2.0)
        components = [first + ".vtx[2]", second + ".vtx[2]"]
        before_first = self._rows(first)
        before_second = self._rows(second)

        result = skin_smooth.smooth(components, strength=1.0)

        self.assertEqual(2, result["meshes"])
        cmds.undo()
        self.assertEqual(before_first, self._rows(first))
        self.assertEqual(before_second, self._rows(second))

    def test_invalid_settings_fail_before_edit(self):
        mesh, _cluster = self._mesh("cloth")
        before = self._rows(mesh)

        with self.assertRaises(ValueError):
            skin_smooth.smooth([mesh + ".vtx[0]"], strength=1.5)

        self.assertEqual(before, self._rows(mesh))

    def test_settings_round_trip_and_invalid_stored_values_fall_back(self):
        self.assertEqual((0.5, 1), skin_smooth.get_settings())
        self.assertEqual((0.25, 3), skin_smooth.set_settings(0.25, 3))
        self.assertEqual((0.25, 3), skin_smooth.get_settings())

        cmds.optionVar(floatValue=(skin_smooth.STRENGTH_OPTION, 2.0))

        self.assertEqual((0.5, 1), skin_smooth.get_settings())

    def test_options_window_builds(self):
        window = skin_smooth.show_options()

        self.assertEqual("ywtaSkinSmoothOptionsWindow", window)
