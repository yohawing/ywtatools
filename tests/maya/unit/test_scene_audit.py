"""Scene Audit の Maya 単体テスト。"""

from unittest import mock

import maya.api.OpenMaya as om
import maya.cmds as cmds

from ywta.test import TestCase
from ywta.utility import scene_audit


class SceneAuditTests(TestCase):
    """read-only 診断と issue 選択を検証する。"""

    def _create_lamina_mesh(self):
        transform = cmds.createNode("transform", name="badMesh")
        selection = om.MSelectionList()
        selection.add(transform)
        parent = selection.getDependNode(0)
        fn_mesh = om.MFnMesh()
        fn_mesh.create(
            [
                om.MPoint(0.0, 0.0, 0.0),
                om.MPoint(1.0, 0.0, 0.0),
                om.MPoint(1.0, 1.0, 0.0),
                om.MPoint(0.0, 1.0, 0.0),
            ],
            [4, 4],
            [0, 1, 2, 3, 0, 1, 2, 3],
            parent=parent,
        )
        return cmds.listRelatives(transform, shapes=True, fullPath=True)[0]

    def test_duplicate_short_names_include_long_paths(self):
        first_group = cmds.createNode("transform", name="first_group")
        second_group = cmds.createNode("transform", name="second_group")
        cmds.createNode("transform", name="control", parent=first_group)
        cmds.createNode("transform", name="control", parent=second_group)

        duplicates = scene_audit.find_duplicate_short_names()

        item = next(entry for entry in duplicates if entry["name"] == "control")
        self.assertEqual(["|first_group|control", "|second_group|control"], item["nodes"])

    def test_duplicate_shape_names_are_not_transform_collisions(self):
        """別階層の同名shapeをrig transform名の衝突として報告しない。"""
        first_group = cmds.createNode("transform", name="first_group")
        second_group = cmds.createNode("transform", name="second_group")
        first = cmds.createNode("transform", name="first", parent=first_group)
        second = cmds.createNode("transform", name="second", parent=second_group)
        cmds.createNode("nurbsCurve", name="displayShape", parent=first)
        cmds.createNode("nurbsCurve", name="displayShape", parent=second)

        duplicates = scene_audit.find_duplicate_short_names()

        self.assertNotIn("displayShape", {entry["name"] for entry in duplicates})

    def test_duplicate_joint_names_are_transform_collisions(self):
        """transform派生のjointも同名階層衝突として報告する。"""
        first_group = cmds.createNode("transform", name="first_group")
        second_group = cmds.createNode("transform", name="second_group")
        cmds.createNode("joint", name="elbow_jnt", parent=first_group)
        cmds.createNode("joint", name="elbow_jnt", parent=second_group)

        duplicates = scene_audit.find_duplicate_short_names()

        item = next(entry for entry in duplicates if entry["name"] == "elbow_jnt")
        self.assertEqual(
            ["|first_group|elbow_jnt", "|second_group|elbow_jnt"],
            item["nodes"],
        )

    def test_lamina_and_non_manifold_components_are_reported(self):
        shape = self._create_lamina_mesh()

        result = scene_audit.audit_mesh(shape)

        self.assertEqual(1, len(result["lamina_faces"]))
        self.assertEqual(4, len(result["non_manifold_vertices"]))
        self.assertEqual(4, len(result["non_manifold_edges"]))

    def test_clean_mesh_has_no_topology_issues(self):
        mesh = cmds.polyCube(name="cleanMesh")[0]
        shape = cmds.listRelatives(mesh, shapes=True, fullPath=True)[0]

        result = scene_audit.audit_mesh(shape)

        self.assertFalse(any(result[category] for category in scene_audit.ISSUE_CATEGORIES))

    def test_zero_area_face_is_reported_read_only(self):
        """world面積0のfaceをmesh変更なしで報告する。"""
        mesh = cmds.createNode("transform", name="flatMesh")
        selection = om.MSelectionList()
        selection.add(mesh)
        function = om.MFnMesh()
        function.create(
            [om.MPoint(0, 0, 0), om.MPoint(1, 0, 0), om.MPoint(2, 0, 0)],
            [3],
            [0, 1, 2],
            parent=selection.getDependNode(0),
        )
        shape = cmds.listRelatives(mesh, shapes=True, fullPath=True)[0]
        before = cmds.polyEvaluate(mesh, vertex=True), cmds.polyEvaluate(mesh, face=True)

        result = scene_audit.audit_mesh(shape)

        self.assertEqual([shape + ".f[0]"], result["zero_area_faces"])
        self.assertEqual(before, (cmds.polyEvaluate(mesh, vertex=True), cmds.polyEvaluate(mesh, face=True)))

    def test_select_issues_can_limit_categories(self):
        shape = self._create_lamina_mesh()
        report = {
            "duplicate_short_names": [],
            "meshes": [scene_audit.audit_mesh(shape)],
        }

        selected = scene_audit.select_issues(report, categories=["lamina_faces"], include_duplicate_names=False)

        self.assertEqual(1, len(selected))
        self.assertIn(".f[", selected[0])
        self.assertEqual(selected, cmds.ls(selection=True, flatten=True, long=True))

    def test_implicit_issue_selection_does_not_reuse_stale_report(self):
        """report省略時は前scene相当のglobal cacheではなく再監査する。"""
        stale = cmds.createNode("transform", name="stale_issue")
        scene_audit._LAST_REPORT = {
            "duplicate_short_names": [{"name": "stale_issue", "nodes": [stale]}],
            "meshes": [],
        }
        cmds.select(stale, replace=True)

        selected = scene_audit.select_issues()

        self.assertEqual([], selected)
        self.assertFalse(cmds.ls(selection=True))

    def test_empty_categories_selects_no_mesh_components(self):
        """明示した空カテゴリを全カテゴリへ読み替えない。"""
        shape = self._create_lamina_mesh()
        report = {
            "duplicate_short_names": [],
            "meshes": [scene_audit.audit_mesh(shape)],
        }

        selected = scene_audit.select_issues(
            report,
            categories=[],
            include_duplicate_names=False,
        )

        self.assertEqual([], selected)
        self.assertFalse(cmds.ls(selection=True))

    def test_invalid_report_is_rejected_before_selection_change(self):
        """壊れたreportで現在selectionをclearしない。"""
        sentinel = cmds.spaceLocator(name="sentinel")[0]
        cmds.select(sentinel, replace=True)

        with self.assertRaises(ValueError):
            scene_audit.select_issues([])

        self.assertEqual([sentinel], cmds.ls(selection=True))

    def test_audit_scene_summary_counts_components(self):
        self._create_lamina_mesh()

        report = scene_audit.audit_scene()

        self.assertEqual(1, report["summary"]["affected_meshes"])
        self.assertEqual(9, report["summary"]["mesh_issue_components"])
        self.assertEqual(4, report["summary"]["non_manifold_vertices"])
        self.assertEqual(4, report["summary"]["non_manifold_edges"])
        self.assertEqual(1, report["summary"]["lamina_faces"])
        self.assertEqual(0, report["summary"]["zero_area_faces"])

    def test_audit_scene_records_mesh_scan_error_and_continues(self):
        mesh = cmds.polyCube(name="brokenMesh")[0]
        shape = cmds.listRelatives(mesh, shapes=True, fullPath=True)[0]

        with mock.patch.object(scene_audit, "audit_mesh", side_effect=RuntimeError("broken")):
            report = scene_audit.audit_scene()

        self.assertEqual(1, report["summary"]["scan_errors"])
        self.assertEqual(shape, report["errors"][0]["shape"])

    def test_selected_audit_only_scans_selected_mesh(self):
        """選択外の不正meshを局所監査結果に混ぜない。"""
        bad_shape = self._create_lamina_mesh()
        clean = cmds.polyCube(name="selectedCleanMesh")[0]
        cmds.select(clean, replace=True)

        report = scene_audit.audit_selected_meshes()

        self.assertEqual([], report["meshes"])
        self.assertEqual(0, report["summary"]["affected_meshes"])
        self.assertNotIn(bad_shape, [item["shape"] for item in report["meshes"]])
        self.assertEqual([], report["duplicate_short_names"])

    def test_selected_audit_accepts_mesh_component(self):
        """component選択から所属meshを解決する。"""
        shape = self._create_lamina_mesh()
        transform = cmds.listRelatives(shape, parent=True, fullPath=True)[0]
        cmds.select(transform + ".f[0]", replace=True)

        report = scene_audit.audit_selected_meshes()

        self.assertEqual([shape], [item["shape"] for item in report["meshes"]])

    def test_selected_audit_rejects_non_mesh_selection(self):
        locator = cmds.spaceLocator(name="notMesh")[0]
        cmds.select(locator, replace=True)

        with self.assertRaises(ValueError):
            scene_audit.audit_selected_meshes()

        self.assertEqual([locator], cmds.ls(selection=True))

    def test_window_builds(self):
        """Scene Auditの局所監査buttonを含むcmds UIを構築できる。"""
        self.assertEqual("ywtaSceneAuditWindow", scene_audit.show())
