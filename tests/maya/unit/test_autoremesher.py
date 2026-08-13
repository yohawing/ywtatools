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
