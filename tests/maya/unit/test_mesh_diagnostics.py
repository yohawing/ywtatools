"""Maya mesh診断のcomponent選択を検証する。"""

import unittest

import maya.api.OpenMaya as om2
import maya.cmds as cmds

from ywta.mesh import mesh_diagnostics


class MeshDiagnosticsMayaTests(unittest.TestCase):
    """実Maya meshで診断選択を検証する。"""

    def setUp(self):
        cmds.file(new=True, force=True)

    def tearDown(self):
        cmds.file(new=True, force=True)

    def test_selects_winding_conflict_edge(self):
        transform = cmds.createNode("transform", name="DiagnosticMesh")
        selection = om2.MSelectionList()
        selection.add(transform)
        parent = selection.getDependNode(0)
        points = [om2.MPoint(0, 0, 0), om2.MPoint(1, 0, 0), om2.MPoint(0, 1, 0), om2.MPoint(1, 1, 0)]
        om2.MFnMesh().create(points, [3, 3], [0, 1, 2, 0, 1, 3], parent=parent)
        cmds.select(transform, replace=True)

        report = mesh_diagnostics.select_issue("winding")
        self.assertEqual(report.winding_conflict_edges, [(0, 1)])
        selected = cmds.ls(selection=True, flatten=True) or []
        self.assertEqual(len(selected), 1)
        self.assertTrue(selected[0].endswith(".e[0]"))


if __name__ == "__main__":
    unittest.main()
