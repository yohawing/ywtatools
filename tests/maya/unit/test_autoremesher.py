"""
AutoRemesher Node のテスト

autoRemesherNode（maya/cpp/src/autoRemesherNode.cpp、maya/plug-ins/<version>/ywtatools.mll）
のノード登録・アトリビュートデフォルト・enable=off時のパススルー・enable=on時のクアッド
リメッシュを検証する。

プラグイン (.mll) がビルドされていない/ロードできない環境ではモジュール単位でスキップする。
"""

import unittest

import maya.api.OpenMaya as om2
import maya.cmds as cmds

PLUGIN_NAME = "ywtatools"

try:
    if not cmds.pluginInfo(PLUGIN_NAME, query=True, loaded=True):
        cmds.loadPlugin(PLUGIN_NAME)
    PLUGIN_LOADED = bool(cmds.pluginInfo(PLUGIN_NAME, query=True, loaded=True))
except RuntimeError:
    PLUGIN_LOADED = False


@unittest.skipUnless(
    PLUGIN_LOADED, f"'{PLUGIN_NAME}' プラグイン(.mll)がロードできないためスキップします。"
)
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


if __name__ == "__main__":
    unittest.main()
