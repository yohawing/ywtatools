"""Maya 2024でHair Tube作成・curve編集・再生成・Undoを検証する。"""

import json
import unittest

import maya.api.OpenMaya as om2
import maya.cmds as cmds

from ywta.mesh import hair_tube


def _make_source():
    """2 stationのopen quad tubeを作る。"""
    transform = cmds.createNode("transform", name="HairTubeSource")
    selection = om2.MSelectionList()
    selection.add(transform)
    parent = selection.getDependNode(0)
    points = [
        om2.MPoint(-0.5, -0.5, 0.0),
        om2.MPoint(0.5, -0.5, 0.0),
        om2.MPoint(0.5, 0.5, 0.0),
        om2.MPoint(-0.5, 0.5, 0.0),
        om2.MPoint(-0.5, -0.5, 1.0),
        om2.MPoint(0.5, -0.5, 1.0),
        om2.MPoint(0.5, 0.5, 1.0),
        om2.MPoint(-0.5, 0.5, 1.0),
    ]
    connects = [0, 1, 5, 4, 1, 2, 6, 5, 2, 3, 7, 6, 3, 0, 4, 7]
    om2.MFnMesh().create(points, [4, 4, 4, 4], connects, parent=parent)
    return transform


def _root_edges(transform):
    """z=0断面の4辺componentを返す。"""
    dag_path = hair_tube._mesh_dag_path(transform)
    iterator = om2.MItMeshEdge(dag_path)
    result = []
    while not iterator.isDone():
        if all(iterator.point(side, om2.MSpace.kObject).z == 0.0 for side in (0, 1)):
            result.append(f"{transform}.e[{iterator.index()}]")
        iterator.next()
    return result


class HairTubeMayaTests(unittest.TestCase):
    """実Maya command導線を検証する。"""

    def setUp(self):
        cmds.file(new=True, force=True)
        cmds.undoInfo(state=True)

    def tearDown(self):
        cmds.file(new=True, force=True)

    def test_create_edit_rebuild_and_undo(self):
        """元mesh保持、curve read-back、密度変更、Undoを検証する。"""
        source = _make_source()
        cmds.select(_root_edges(source), replace=True)
        output = hair_tube.create_from_selected_root(segments=3)

        self.assertTrue(cmds.objExists(source))
        self.assertEqual(cmds.polyEvaluate(source, vertex=True), 8)
        self.assertEqual(cmds.polyEvaluate(source, face=True), 4)
        self.assertEqual(cmds.polyEvaluate(output, vertex=True), 16)
        self.assertEqual(cmds.polyEvaluate(output, face=True), 12)
        curve_names = json.loads(cmds.getAttr(f"{output}.ywtaHairTubeCurveNames"))
        self.assertEqual(len(curve_names), 4)

        last_cv = cmds.getAttr(f"{curve_names[0]}.spans")
        cmds.move(-0.25, 0.0, 0.0, f"{curve_names[0]}.cv[{last_cv}]", relative=True, objectSpace=True)
        cmds.select(output, replace=True)
        rebuilt = hair_tube.rebuild_selected(segments=2)
        self.assertEqual(cmds.polyEvaluate(rebuilt, vertex=True), 12)
        self.assertEqual(cmds.polyEvaluate(rebuilt, face=True), 8)
        self.assertLess(cmds.pointPosition(f"{rebuilt}.vtx[8]", local=True)[0], -0.5)
        self.assertEqual(cmds.polyEvaluate(source, vertex=True), 8)

        cmds.undo()
        self.assertTrue(cmds.objExists(output))
        self.assertEqual(cmds.polyEvaluate(output, vertex=True), 16)
        self.assertEqual(cmds.polyEvaluate(source, vertex=True), 8)

        cmds.redo()
        self.assertTrue(cmds.objExists(rebuilt))
        self.assertEqual(cmds.polyEvaluate(rebuilt, vertex=True), 12)
        self.assertEqual(cmds.polyEvaluate(source, vertex=True), 8)

        cmds.select(rebuilt, replace=True)
        lods = hair_tube.generate_lods_selected("1,3")
        self.assertEqual(len(lods), 2)
        self.assertEqual(cmds.polyEvaluate(lods[0], vertex=True), 8)
        self.assertEqual(cmds.polyEvaluate(lods[1], vertex=True), 16)
        self.assertEqual(
            cmds.getAttr(f"{lods[0]}.ywtaHairTubeCurveNames"),
            cmds.getAttr(f"{rebuilt}.ywtaHairTubeCurveNames"),
        )
        cmds.undo()
        self.assertTrue(all(not cmds.objExists(lod) for lod in lods))
        cmds.redo()
        self.assertTrue(all(cmds.objExists(lod) for lod in lods))

    def test_create_undo_and_redo_restore_all_outputs(self):
        """作成操作のUndo/Redoがmeshと4 curveをまとめて復元する。"""
        source = _make_source()
        cmds.select(_root_edges(source), replace=True)
        output = hair_tube.create_from_selected_root(segments=2)
        curve_names = json.loads(cmds.getAttr(f"{output}.ywtaHairTubeCurveNames"))

        cmds.undo()
        self.assertFalse(cmds.objExists(output))
        self.assertTrue(all(not cmds.objExists(name) for name in curve_names))
        self.assertTrue(cmds.objExists(source))

        cmds.redo()
        self.assertTrue(cmds.objExists(output))
        self.assertEqual(cmds.polyEvaluate(output, vertex=True), 12)
        self.assertTrue(all(cmds.objExists(name) for name in curve_names))


if __name__ == "__main__":
    unittest.main()
