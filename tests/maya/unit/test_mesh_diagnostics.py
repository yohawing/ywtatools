"""Maya mesh診断のcomponent選択を検証する。"""

import json
import unittest

import maya.api.OpenMaya as om2
import maya.cmds as cmds

from ywta.mesh import mesh_diagnostics


class MeshDiagnosticsMayaTests(unittest.TestCase):
    """実Maya meshで診断選択を検証する。"""

    def setUp(self):
        cmds.file(new=True, force=True)
        cmds.undoInfo(state=True)

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
        cmds.select(transform, replace=True)
        mesh_diagnostics.safe_repair_selected(True)
        function = mesh_diagnostics._mesh_arrays(transform)[0]

        def direction(face):
            vertices = tuple(function.getPolygonVertices(face))
            for index, vertex in enumerate(vertices):
                following = vertices[(index + 1) % len(vertices)]
                if {vertex, following} == {0, 1}:
                    return vertex == 0
            return None

        self.assertNotEqual(direction(0), direction(1))
        cmds.undo()

    def test_safe_repair_preview_apply_and_undo(self):
        transform = cmds.createNode("transform", name="RepairMesh")
        selection = om2.MSelectionList()
        selection.add(transform)
        parent = selection.getDependNode(0)
        points = [om2.MPoint(0, 0, 0), om2.MPoint(1, 0, 0), om2.MPoint(0, 1, 0), om2.MPoint(2, 0, 0)]
        om2.MFnMesh().create(points, [3, 3], [0, 1, 3, 0, 1, 2], parent=parent)
        function = mesh_diagnostics._mesh_arrays(transform)[0]
        function.setUVs([0.0, 0.1, 0.2, 0.3, 0.4, 0.5], [0.0] * 6, "map1")
        function.assignUVs([3, 3], list(range(6)), "map1")
        cmds.select(transform, replace=True)

        plan = mesh_diagnostics.safe_repair_selected(False)
        self.assertEqual(plan.removed_zero_area_faces, [0])
        self.assertEqual(cmds.polyEvaluate(transform, face=True), 2)
        cmds.select(transform, replace=True)
        mesh_diagnostics.safe_repair_selected(True)
        self.assertEqual(cmds.polyEvaluate(transform, face=True), 1)
        self.assertEqual(mesh_diagnostics._mesh_arrays(transform)[0].numUVs("map1"), 3)
        self.assertEqual(json.loads(cmds.getAttr(f"{transform}.ywtaMeshRepairOldFaceToNew")), [None, 0])
        cmds.undo()
        self.assertEqual(cmds.polyEvaluate(transform, face=True), 2)


if __name__ == "__main__":
    unittest.main()
