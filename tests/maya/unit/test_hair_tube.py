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


def _add_source_attributes(source):
    """UV seam、face color、material、2-joint skin weightを追加する。"""
    function = om2.MFnMesh(hair_tube._mesh_dag_path(source))
    uv_values = []
    for face in range(function.numPolygons):
        for vertex in function.getPolygonVertices(face):
            point = function.getPoint(vertex, om2.MSpace.kObject)
            uv_values.append((face * 0.25 + (vertex % 4) * 0.05, point.z))
    function.setUVs([value[0] for value in uv_values], [value[1] for value in uv_values], "map1")
    function.assignUVs([4] * function.numPolygons, list(range(function.numPolygons * 4)), "map1")

    color_set = function.createColorSet("HairColor", False, om2.MFnMesh.kRGBA)
    colors = []
    face_ids = []
    vertex_ids = []
    for face in range(function.numPolygons):
        for vertex in function.getPolygonVertices(face):
            z = function.getPoint(vertex, om2.MSpace.kObject).z
            colors.append(om2.MColor((z, 0.25, 1.0 - z, 1.0)))
            face_ids.append(face)
            vertex_ids.append(vertex)
    function.setCurrentColorSetName(color_set)
    function.setFaceVertexColors(colors, face_ids, vertex_ids, rep=om2.MFnMesh.kRGBA)

    shaders = []
    for name in ("HairRootMaterial", "HairTipMaterial"):
        material = cmds.shadingNode("lambert", asShader=True, name=name)
        shading_group = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name=f"{name}SG")
        cmds.connectAttr(f"{material}.outColor", f"{shading_group}.surfaceShader", force=True)
        shaders.append(shading_group)
    for face in range(function.numPolygons):
        cmds.sets(f"{source}.f[{face}]", edit=True, forceElement=shaders[face % 2])

    cmds.select(clear=True)
    root_joint = cmds.joint(name="RootBone", position=(0.0, 0.0, 0.0))
    cmds.select(clear=True)
    tip_joint = cmds.joint(name="TipBone", position=(0.0, 0.0, 1.0))
    cluster = cmds.skinCluster([root_joint, tip_joint], source, toSelectedBones=True, normalizeWeights=1)[0]
    for vertex in range(4):
        cmds.skinPercent(cluster, f"{source}.vtx[{vertex}]", transformValue=[(root_joint, 1.0), (tip_joint, 0.0)])
    for vertex in range(4, 8):
        cmds.skinPercent(cluster, f"{source}.vtx[{vertex}]", transformValue=[(root_joint, 0.0), (tip_joint, 1.0)])


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
        _add_source_attributes(source)
        cmds.select(_root_edges(source), replace=True)
        output = hair_tube.create_from_selected_root(segments=3)

        self.assertTrue(cmds.objExists(source))
        self.assertEqual(cmds.polyEvaluate(source, vertex=True), 8)
        self.assertEqual(cmds.polyEvaluate(source, face=True), 4)
        self.assertEqual(cmds.polyEvaluate(output, vertex=True), 16)
        self.assertEqual(cmds.polyEvaluate(output, face=True), 12)
        output_function = om2.MFnMesh(hair_tube._mesh_dag_path(output))
        first_u = output_function.getUV(output_function.getPolygonUVid(0, 1, "map1"), "map1")[0]
        seam_u = output_function.getUV(output_function.getPolygonUVid(1, 0, "map1"), "map1")[0]
        self.assertAlmostEqual(first_u, 0.05)
        self.assertAlmostEqual(seam_u, 0.30)
        self.assertNotAlmostEqual(first_u, seam_u)
        colors = output_function.getFaceVertexColors("HairColor")
        self.assertAlmostEqual(colors[output_function.getFaceVertexIndex(0, 2)].r, 1.0 / 3.0)
        shaders, shader_indices = output_function.getConnectedShaders(0)
        shader_names = [om2.MFnDependencyNode(shader).name() for shader in shaders]
        self.assertEqual(
            [shader_names[index] for index in shader_indices[:4]],
            ["HairRootMaterialSG", "HairTipMaterialSG", "HairRootMaterialSG", "HairTipMaterialSG"],
        )
        output_skin = cmds.ls(cmds.listHistory(output), type="skinCluster")[0]
        weights = cmds.skinPercent(output_skin, f"{output}.vtx[4]", query=True, value=True)
        self.assertAlmostEqual(sum(weights), 1.0)
        self.assertAlmostEqual(weights[0], 2.0 / 3.0)
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
        rebuilt_function = om2.MFnMesh(hair_tube._mesh_dag_path(rebuilt))
        self.assertGreater(rebuilt_function.numUVs("map1"), 0)
        self.assertIn("HairColor", rebuilt_function.getColorSetNames())
        self.assertEqual(len(cmds.ls(cmds.listHistory(rebuilt), type="skinCluster")), 1)

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
        self.assertGreater(om2.MFnMesh(hair_tube._mesh_dag_path(lods[0])).numUVs("map1"), 0)
        self.assertEqual(len(cmds.ls(cmds.listHistory(lods[0]), type="skinCluster")), 1)
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

    def test_attribute_apply_failure_rolls_back_partial_output(self):
        """属性適用例外でも生成途中のmeshを残さない。"""
        source = _make_source()
        cmds.select(_root_edges(source), replace=True)
        original = hair_tube._apply_attribute_payload

        def fail_apply(_output, _payload):
            raise RuntimeError("injected attribute failure")

        hair_tube._apply_attribute_payload = fail_apply
        try:
            with self.assertRaisesRegex(RuntimeError, "injected attribute failure"):
                hair_tube.create_from_selected_root(segments=2)
        finally:
            hair_tube._apply_attribute_payload = original
        self.assertTrue(cmds.objExists(source))
        self.assertFalse(cmds.objExists("HairTubeSource_HairTube"))
        self.assertFalse(cmds.objExists("HairTubeSource_HairTubeRail1"))


if __name__ == "__main__":
    unittest.main()
