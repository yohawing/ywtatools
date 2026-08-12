"""mapping-based skinned mesh分割のMaya単体テスト。"""

import maya.api.OpenMaya as om
import maya.api.OpenMayaAnim as oma
import maya.cmds as cmds

from ywta.deform import separate_skinned
from ywta.deform import skin_io
from ywta.test import TestCase


class SeparateSkinnedTests(TestCase):
    """coincident shell、属性転送、Undoを検証する。"""

    def _source(self):
        """同位置の2 shellへ異なるweightとmaterialを設定する。"""
        first = cmds.polyPlane(name="first", width=2, height=2, subdivisionsX=1, subdivisionsY=1)[0]
        second = cmds.polyPlane(name="second", width=2, height=2, subdivisionsX=1, subdivisionsY=1)[0]
        source = cmds.polyUnite(first, second, constructionHistory=False, name="body")[0]
        cmds.select(clear=True)
        left = cmds.joint(name="left_joint", position=(-1, 0, 0))
        cmds.select(clear=True)
        right = cmds.joint(name="right_joint", position=(1, 0, 0))
        cluster = cmds.skinCluster([left, right], source, toSelectedBones=True, normalizeWeights=1)[0]
        for index in range(8):
            values = [(left, 1.0), (right, 0.0)] if index < 4 else [(left, 0.0), (right, 1.0)]
            cmds.skinPercent(cluster, "{}.vtx[{}]".format(source, index), transformValue=values)

        red = cmds.shadingNode("lambert", asShader=True, name="red_material")
        blue = cmds.shadingNode("lambert", asShader=True, name="blue_material")
        red_sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name="red_materialSG")
        blue_sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name="blue_materialSG")
        cmds.connectAttr(red + ".outColor", red_sg + ".surfaceShader")
        cmds.connectAttr(blue + ".outColor", blue_sg + ".surfaceShader")
        cmds.sets(source + ".f[0]", edit=True, forceElement=red_sg)
        cmds.sets(source + ".f[1]", edit=True, forceElement=blue_sg)
        cmds.polyColorSet(source, create=True, colorSet="shell_color")
        cmds.polyColorSet(source, currentColorSet=True, colorSet="shell_color")
        cmds.polyColorPerVertex(source + ".vtx[0:3]", rgb=(1.0, 0.0, 0.0))
        cmds.polyColorPerVertex(source + ".vtx[4:7]", rgb=(0.0, 0.0, 1.0))
        return source, left, right, (red_sg, blue_sg)

    @staticmethod
    def _weights(mesh):
        """pieceのphysical influence名とdense weightを返す。"""
        shape = skin_io._mesh_shape(mesh)
        cluster = skin_io._skin_cluster(shape)
        function = oma.MFnSkinCluster(skin_io._depend_node(cluster))
        influences = [path.fullPathName().rsplit("|", 1)[-1] for path in function.influenceObjects()]
        count = om.MFnMesh(skin_io._dag_path(shape)).numVertices
        values, influence_count = function.getWeights(skin_io._dag_path(shape), skin_io._vertex_component(count))
        rows = [list(values[index * influence_count : (index + 1) * influence_count]) for index in range(count)]
        return influences, rows

    def test_separate_preserves_exact_weights_uvs_and_materials(self):
        """同位置shellでも元index mappingでweightとface属性を分離する。"""
        source, left, right, shading_groups = self._source()
        source_uuid = cmds.ls(source, uuid=True)[0]

        result = separate_skinned.separate(source)

        self.assertEqual(source_uuid, cmds.ls(source, uuid=True)[0])
        self.assertEqual(2, len(result["pieces"]))
        expected_influences = (left, right)
        expected_colors = ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0))
        source_function = om.MFnMesh(skin_io._dag_path(skin_io._mesh_shape(source)))
        for piece, expected_influence, shading_group, expected_color in zip(
            result["pieces"], expected_influences, shading_groups, expected_colors
        ):
            mesh = piece["mesh"]
            function = om.MFnMesh(skin_io._dag_path(skin_io._mesh_shape(mesh)))
            self.assertEqual(4, function.numVertices)
            self.assertGreater(function.numUVs(), 0)
            self.assertIn("shell_color", function.getColorSetNames())
            color = function.getFaceVertexColors("shell_color")[0]
            for actual, expected in zip((color.r, color.g, color.b), expected_color):
                self.assertAlmostEqual(expected, actual)
            source_normals = source_function.getFaceVertexNormals(piece["original_faces"][0], om.MSpace.kWorld)
            piece_normals = function.getFaceVertexNormals(0, om.MSpace.kWorld)
            for actual, expected in zip(piece_normals, source_normals):
                self.assertAlmostEqual(expected.x, actual.x)
                self.assertAlmostEqual(expected.y, actual.y)
                self.assertAlmostEqual(expected.z, actual.z)
            influences, rows = self._weights(mesh)
            index = influences.index(expected_influence)
            self.assertTrue(all(row[index] > 0.999 for row in rows))
            connected, assignments = function.getConnectedShaders(0)
            names = [om.MFnDependencyNode(item).name() for item in connected]
            self.assertEqual(shading_group, names[assignments[0]])

    def test_separate_is_single_undoable_action(self):
        """出力pieceだけを1回でUndoし、元meshを維持する。"""
        source, _left, _right, _shading_groups = self._source()
        cmds.select(source, replace=True)

        result = separate_skinned.separate(source)
        piece_names = [piece["mesh"] for piece in result["pieces"]]
        self.assertEqual(set(piece_names), set(cmds.ls(selection=True, long=True)))

        cmds.undo()

        self.assertTrue(cmds.objExists(source))
        self.assertTrue(all(not cmds.objExists(name) for name in piece_names))
        self.assertEqual(cmds.ls(source, long=True), cmds.ls(selection=True, long=True))

    def test_separate_preserves_source_bind_deformation(self):
        """分割後もsourceのbindPreMatrix契約と同じjoint変形を行う。"""
        source, left, right, _shading_groups = self._source()
        cmds.setAttr(left + ".translateY", 1.5)
        cmds.setAttr(right + ".translateY", -2.0)

        result = separate_skinned.separate(source)

        source_function = om.MFnMesh(skin_io._dag_path(skin_io._mesh_shape(source)))
        for left_y, right_y in ((1.5, -2.0), (-1.0, 3.0)):
            cmds.setAttr(left + ".translateY", left_y)
            cmds.setAttr(right + ".translateY", right_y)
            source_points = source_function.getPoints(om.MSpace.kWorld)
            for piece in result["pieces"]:
                piece_function = om.MFnMesh(skin_io._dag_path(skin_io._mesh_shape(piece["mesh"])))
                piece_points = piece_function.getPoints(om.MSpace.kWorld)
                for point, original_index in zip(piece_points, piece["original_vertices"]):
                    expected = source_points[original_index]
                    self.assertAlmostEqual(expected.x, point.x)
                    self.assertAlmostEqual(expected.y, point.y)
                    self.assertAlmostEqual(expected.z, point.z)

    def test_single_shell_rejects_before_edit(self):
        """1 shell meshでは出力を作成しない。"""
        mesh = cmds.polyPlane(name="single")[0]
        cmds.select(clear=True)
        joint = cmds.joint(name="joint")
        cmds.skinCluster(joint, mesh, toSelectedBones=True)

        with self.assertRaises(ValueError):
            separate_skinned.separate(mesh)

        self.assertFalse(cmds.objExists("single_shell01"))
