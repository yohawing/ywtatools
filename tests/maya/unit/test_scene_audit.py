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

    def test_audit_scene_summary_counts_components(self):
        self._create_lamina_mesh()

        report = scene_audit.audit_scene()

        self.assertEqual(1, report["summary"]["affected_meshes"])
        self.assertEqual(9, report["summary"]["mesh_issue_components"])
        self.assertEqual(4, report["summary"]["non_manifold_vertices"])
        self.assertEqual(4, report["summary"]["non_manifold_edges"])
        self.assertEqual(1, report["summary"]["lamina_faces"])

    def test_audit_scene_records_mesh_scan_error_and_continues(self):
        mesh = cmds.polyCube(name="brokenMesh")[0]
        shape = cmds.listRelatives(mesh, shapes=True, fullPath=True)[0]

        with mock.patch.object(scene_audit, "audit_mesh", side_effect=RuntimeError("broken")):
            report = scene_audit.audit_scene()

        self.assertEqual(1, report["summary"]["scan_errors"])
        self.assertEqual(shape, report["errors"][0]["shape"])
