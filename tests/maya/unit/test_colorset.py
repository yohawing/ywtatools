"""Maya Color Set ユーティリティの実メッシュテスト。"""

import unittest

import maya.api.OpenMaya as om2
import maya.cmds as cmds

from ywta.mesh import colorset


class ColorSetTests(unittest.TestCase):
    """Color Set の作成と読み戻しを検証する。"""

    def setUp(self):
        """テストごとに空のシーンを作成する。"""
        cmds.file(new=True, force=True)

    def tearDown(self):
        """作成したシーンを破棄する。"""
        cmds.file(new=True, force=True)

    def test_create_and_read_vertex_colors(self):
        """Color Set 作成後の function set で頂点色を書き込む。"""
        mesh = cmds.polyCube()[0]
        vertex_count = cmds.polyEvaluate(mesh, vertex=True)
        expected = (0.25, 0.5, 0.75)
        values = om2.MColorArray([om2.MColor((*expected, 1.0)) for _ in range(vertex_count)])

        colorset.create_colorset(mesh, "ywtaTest", values)

        self.assertEqual(["ywtaTest"], colorset.get_colorset_list(mesh))
        readback = colorset.get_colorset(mesh, "ywtaTest")
        self.assertTrue(readback)
        for color in readback:
            self.assertAlmostEqual(expected[0], color.r)
            self.assertAlmostEqual(expected[1], color.g)
            self.assertAlmostEqual(expected[2], color.b)


if __name__ == "__main__":
    unittest.main()
