"""
AutoRemesher Node のテスト

autoRemesherNode（maya/cpp/src/autoRemesherNode.cpp、maya/plug-ins/<version>/ywtatools.mll）
のノード登録・アトリビュートデフォルト・enable=off時のパススルー・enable=on時のクアッド
リメッシュを検証する。

プラグイン (.mll) がビルドされていない/ロードできない環境ではモジュール単位でスキップする。
"""

import unittest
from unittest import mock

import maya.api.OpenMaya as om2
import maya.cmds as cmds

PLUGIN_NAME = "ywtatools"

try:
    if not cmds.pluginInfo(PLUGIN_NAME, query=True, loaded=True):
        cmds.loadPlugin(PLUGIN_NAME)
    PLUGIN_LOADED = bool(cmds.pluginInfo(PLUGIN_NAME, query=True, loaded=True))
except RuntimeError:
    PLUGIN_LOADED = False


@unittest.skipUnless(PLUGIN_LOADED, f"'{PLUGIN_NAME}' プラグイン(.mll)がロードできないためスキップします。")
class TestAutoRemesherNode(unittest.TestCase):
    """AutoRemesherNode のテストクラス"""

    def setUp(self):
        """テスト前の準備"""
        cmds.file(new=True, force=True)

    def tearDown(self):
        """テスト後のクリーンアップ"""
        cmds.file(new=True, force=True)

    def test_node_creation(self):
        """ノードが作成できるかテスト"""
        node = cmds.createNode("autoRemesherNode")
        self.assertTrue(cmds.objExists(node))
        self.assertEqual(cmds.nodeType(node), "autoRemesherNode")

    def test_attribute_defaults(self):
        """アトリビュートのデフォルト値のテスト"""
        node = cmds.createNode("autoRemesherNode")
        self.assertFalse(cmds.getAttr(f"{node}.enable"))
        self.assertEqual(cmds.getAttr(f"{node}.targetCount"), 8000)
        self.assertAlmostEqual(cmds.getAttr(f"{node}.adaptivity"), 1.0, places=6)
        self.assertAlmostEqual(cmds.getAttr(f"{node}.edgeScaling"), 1.0, places=6)
        self.assertEqual(cmds.getAttr(f"{node}.modelType"), 0)
        self.assertAlmostEqual(cmds.getAttr(f"{node}.sharpEdgeDegrees"), 90.0, places=6)
        self.assertAlmostEqual(cmds.getAttr(f"{node}.smoothNormalDegrees"), 0.0, places=6)

    def test_enable_false_passthrough(self):
        """enable=false のとき inMesh がそのまま outMesh に渡されるかテスト"""
        cube = cmds.polyCube()[0]
        cmds.polyTriangulate(cube)
        shape = cmds.listRelatives(cube, shapes=True)[0]

        node = cmds.createNode("autoRemesherNode")
        cmds.connectAttr(f"{shape}.outMesh", f"{node}.inMesh")

        out_transform = cmds.createNode("transform")
        out_shape = cmds.createNode("mesh", parent=out_transform)
        cmds.connectAttr(f"{node}.outMesh", f"{out_shape}.inMesh")

        in_face_count = cmds.polyEvaluate(shape, face=True)
        in_vertex_count = cmds.polyEvaluate(shape, vertex=True)
        out_face_count = cmds.polyEvaluate(out_shape, face=True)
        out_vertex_count = cmds.polyEvaluate(out_shape, vertex=True)

        self.assertEqual(in_face_count, out_face_count)
        self.assertEqual(in_vertex_count, out_vertex_count)

    def test_enable_true_remesh(self):
        """enable=true のとき出力がクアッド主体のリメッシュ結果になるかテスト"""
        cube = cmds.polyCube(subdivisionsX=4, subdivisionsY=4, subdivisionsZ=4)[0]
        cmds.polyTriangulate(cube)
        shape = cmds.listRelatives(cube, shapes=True)[0]

        node = cmds.createNode("autoRemesherNode")
        cmds.connectAttr(f"{shape}.outMesh", f"{node}.inMesh")
        cmds.setAttr(f"{node}.enable", True)
        cmds.setAttr(f"{node}.targetCount", 400)

        out_transform = cmds.createNode("transform")
        out_shape = cmds.createNode("mesh", parent=out_transform)
        cmds.connectAttr(f"{node}.outMesh", f"{out_shape}.inMesh")

        out_face_count = cmds.polyEvaluate(out_shape, face=True)
        self.assertGreater(out_face_count, 0)

        selection = om2.MSelectionList()
        selection.add(out_shape)
        dag_path = selection.getDagPath(0)
        quad_count = 0
        tri_count = 0
        poly_iter = om2.MItMeshPolygon(dag_path)
        while not poly_iter.isDone():
            vertex_count = poly_iter.polygonVertexCount()
            if vertex_count == 4:
                quad_count += 1
            elif vertex_count == 3:
                tri_count += 1
            poly_iter.next()

        self.assertGreater(quad_count, tri_count)

    def test_create_remesh_node_with_params(self):
        """create_remesh_node() に渡したパラメータがノードのアトリビュートに反映されるかテスト"""
        import ywta.mesh.autoremesher as autoremesher

        cube = cmds.polyCube()[0]
        cmds.select(cube)

        node = autoremesher.create_remesh_node(
            target_count=2000,
            adaptivity=0.5,
            edge_scaling=1.5,
            model_type=1,
        )

        self.assertTrue(cmds.objExists(node))
        self.assertEqual(cmds.getAttr(f"{node}.targetCount"), 2000)
        self.assertAlmostEqual(cmds.getAttr(f"{node}.adaptivity"), 0.5, places=6)
        self.assertAlmostEqual(cmds.getAttr(f"{node}.edgeScaling"), 1.5, places=6)
        self.assertEqual(cmds.getAttr(f"{node}.modelType"), 1)
        self.assertTrue(cmds.getAttr(f"{node}.enable"))
        self.assertEqual(cmds.ls(selection=True), [node])

    def test_create_remesh_node_with_sharp_and_smooth_params(self):
        """sharp_edge_degrees / smooth_normal_degrees がノードのアトリビュートに反映されるかテスト"""
        import ywta.mesh.autoremesher as autoremesher

        cube = cmds.polyCube()[0]
        cmds.select(cube)

        node = autoremesher.create_remesh_node(
            sharp_edge_degrees=45.0,
            smooth_normal_degrees=30.0,
        )

        self.assertTrue(cmds.objExists(node))
        self.assertAlmostEqual(cmds.getAttr(f"{node}.sharpEdgeDegrees"), 45.0, places=6)
        self.assertAlmostEqual(cmds.getAttr(f"{node}.smoothNormalDegrees"), 30.0, places=6)

    def test_create_remesh_node_copies_parented_source_world_transform(self):
        """親子化・変形済み入力のワールド行列と頂点位置を出力へ引き継ぐかテスト"""
        import ywta.mesh.autoremesher as autoremesher

        parent = cmds.group(empty=True, name="remeshSourceParent")
        cmds.xform(parent, translation=(3.0, -2.0, 5.0), rotation=(15.0, 25.0, -10.0), worldSpace=True)
        source = cmds.polyCube(name="remeshSource")[0]
        cmds.parent(source, parent)
        cmds.xform(source, translation=(1.0, 2.0, -4.0), rotation=(20.0, -35.0, 40.0), scale=(2.0, 1.5, 0.75))
        source_shape = cmds.listRelatives(source, shapes=True, noIntermediate=True)[0]
        source_world_matrix = cmds.xform(source, query=True, matrix=True, worldSpace=True)
        source_selection = om2.MSelectionList()
        source_selection.add(source_shape)
        source_points = om2.MFnMesh(source_selection.getDagPath(0)).getPoints(om2.MSpace.kWorld)

        cmds.select(source)
        node = autoremesher.create_remesh_node()
        output_transform = cmds.ls(f"{source}_remeshed", long=True)[0]
        output = cmds.listRelatives(output_transform, shapes=True, noIntermediate=True)[0]

        output_world_matrix = cmds.xform(output_transform, query=True, matrix=True, worldSpace=True)
        for expected, actual in zip(source_world_matrix, output_world_matrix):
            self.assertAlmostEqual(expected, actual, places=5)

        # enable=false で outMesh をパススルーに戻し、ワールド頂点が一致することを検証する。
        cmds.setAttr(f"{node}.enable", False)
        output_selection = om2.MSelectionList()
        output_selection.add(output)
        output_points = om2.MFnMesh(output_selection.getDagPath(0)).getPoints(om2.MSpace.kWorld)
        self.assertEqual(len(source_points), len(output_points))
        for source_point, output_point in zip(source_points, output_points):
            self.assertAlmostEqual(source_point.x, output_point.x, places=5)
            self.assertAlmostEqual(source_point.y, output_point.y, places=5)
            self.assertAlmostEqual(source_point.z, output_point.z, places=5)

    def test_plugin_loader_falls_back_to_versioned_repository_binary(self):
        """module path未設定時はversion別の同梱mllを絶対pathでロードする。"""
        import ywta.mesh.autoremesher as autoremesher

        with (
            mock.patch.object(autoremesher.cmds, "pluginInfo", side_effect=[False, True]),
            mock.patch.object(
                autoremesher.cmds,
                "loadPlugin",
                side_effect=[RuntimeError("not on MAYA_PLUG_IN_PATH"), ["ywtatools"]],
            ) as load_plugin,
            mock.patch.object(autoremesher.cmds, "about", return_value="2024"),
        ):
            self.assertTrue(autoremesher._ensure_plugin_loaded())

        self.assertEqual(load_plugin.call_args_list[0].args[0], "ywtatools")
        self.assertTrue(load_plugin.call_args_list[1].args[0].replace("\\", "/").endswith("maya/plug-ins/2024/ywtatools.mll"))


if __name__ == "__main__":
    unittest.main()
