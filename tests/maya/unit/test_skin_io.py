"""Skin IO の Maya 単体テスト。"""

import copy
from unittest import mock

import maya.cmds as cmds

from ywta.deform import skin_io
from ywta.test import TestCase


class SkinIoTests(TestCase):
    """同一トポロジーの保存・復元 contract を検証する。"""

    def setUp(self):
        if cmds.optionVar(exists=skin_io.SURFACE_ASSOCIATION_OPTION):
            cmds.optionVar(remove=skin_io.SURFACE_ASSOCIATION_OPTION)
        self.mesh = cmds.polyPlane(name="cloth", subdivisionsX=1, subdivisionsY=1)[0]
        cmds.select(clear=True)
        self.joint_a = cmds.joint(name="root_jnt", position=(-1.0, 0.0, 0.0))
        cmds.select(clear=True)
        self.joint_b = cmds.joint(name="tip_jnt", position=(1.0, 0.0, 0.0))
        self.cluster = cmds.skinCluster(self.joint_a, self.joint_b, self.mesh, toSelectedBones=True, normalizeWeights=1)[0]
        vertices = cmds.ls(self.mesh + ".vtx[*]", flatten=True)
        positions = [cmds.xform(vertex, query=True, worldSpace=True, translation=True)[0] for vertex in vertices]
        minimum = min(positions)
        extent = max(positions) - minimum
        for position, vertex in zip(positions, vertices):
            weight = (position - minimum) / extent
            cmds.skinPercent(
                self.cluster,
                vertex,
                transformValue=((self.joint_a, 1.0 - weight), (self.joint_b, weight)),
            )

    def test_capture_and_apply_restore_weights(self):
        data = skin_io.capture(self.mesh)
        vertices = cmds.ls(self.mesh + ".vtx[*]", flatten=True)
        for vertex in vertices:
            cmds.skinPercent(
                self.cluster,
                vertex,
                transformValue=((self.joint_a, 1.0), (self.joint_b, 0.0)),
            )
        modified = skin_io.capture(self.mesh)["weights"]

        skin_io.apply(self.mesh, data)

        restored = skin_io.capture(self.mesh)
        for expected_row, actual_row in zip(data["weights"], restored["weights"]):
            self.assertEqual([entry[0] for entry in expected_row], [entry[0] for entry in actual_row])
            for expected, actual in zip(expected_row, actual_row):
                self.assertAlmostEqual(expected[1], actual[1], places=6)

        cmds.undo()
        self.assertEqual(modified, skin_io.capture(self.mesh)["weights"])
        cmds.redo()
        redone = skin_io.capture(self.mesh)["weights"]
        for expected_row, actual_row in zip(data["weights"], redone):
            for expected, actual in zip(expected_row, actual_row):
                self.assertAlmostEqual(expected[1], actual[1], places=6)

    def test_direct_apply_rejects_locked_influence_without_weight_change(self):
        """locked influenceがあるtargetへ部分的なbulk writeを行わない。"""
        data = skin_io.capture(self.mesh)
        vertex = self.mesh + ".vtx[0]"
        cmds.skinPercent(
            self.cluster,
            vertex,
            transformValue=((self.joint_a, 0.25), (self.joint_b, 0.75)),
        )
        before = skin_io.capture(self.mesh)["weights"]
        cmds.setAttr(self.joint_b + ".lockInfluenceWeights", True)

        with self.assertRaises(ValueError):
            skin_io.apply(self.mesh, data)

        self.assertEqual(before, skin_io.capture(self.mesh)["weights"])

    def test_save_and_read_round_trip(self):
        path = self.get_temp_filename("weights.json")

        skin_io.save(self.mesh, path)
        data = skin_io.read(path)

        self.assertEqual(skin_io.FORMAT, data["format"])
        self.assertEqual(4, data["mesh"]["topology"]["vertex_count"])
        self.assertEqual(2, len(data["influences"]))
        self.assertEqual(4, len(data["mesh"]["geometry"]["points"]))
        self.assertEqual(cmds.currentUnit(query=True, linear=True), data["scene"]["linear_unit"])
        self.assertEqual(cmds.upAxis(query=True, axis=True), data["scene"]["up_axis"])

    def test_temporary_skin_round_trip_uses_validated_engine(self):
        path = self.get_temp_filename("temp_skin.json")
        expected = skin_io.capture(self.mesh)["weights"]
        skin_io.save_temp(self.mesh, file_path=path)
        for vertex in cmds.ls(self.mesh + ".vtx[*]", flatten=True):
            cmds.skinPercent(
                self.cluster,
                vertex,
                transformValue=((self.joint_a, 1.0), (self.joint_b, 0.0)),
            )

        cluster = skin_io.load_temp(self.mesh, file_path=path)

        self.assertEqual(self.cluster, cluster)
        actual = skin_io.capture(self.mesh)["weights"]
        self.assertEqual(expected, actual)

    def test_temporary_skin_transfer_mode_validates_bool(self):
        with self.assertRaises(ValueError):
            skin_io.load_temp(self.mesh, transfer_mode="yes")

    def test_apply_creates_skin_cluster_on_unskinned_mesh(self):
        data = skin_io.capture(self.mesh)
        target = cmds.duplicate(self.mesh, name="unskinned_target")[0]
        cmds.delete(target, constructionHistory=True)
        sentinel = cmds.spaceLocator(name="selection_sentinel")[0]
        cmds.select(sentinel, replace=True)

        cluster = skin_io.apply(target, data)

        self.assertTrue(cmds.objExists(cluster))
        self.assertEqual([sentinel], cmds.ls(selection=True))
        restored = skin_io.capture(target)
        self.assertEqual(data["weights"], restored["weights"])

        cmds.undo()
        target_shape = cmds.listRelatives(target, shapes=True, fullPath=True)[0]
        self.assertIsNone(skin_io._skin_cluster(target_shape))
        cmds.redo()
        redone = skin_io.capture(target)
        self.assertEqual(data["weights"], redone["weights"])

    def test_apply_zeros_existing_extra_influence(self):
        data = skin_io.capture(self.mesh)
        cmds.select(clear=True)
        extra = cmds.joint(name="extra_jnt", position=(0.0, 1.0, 0.0))
        cmds.skinCluster(self.cluster, edit=True, addInfluence=extra, weight=1.0)

        skin_io.apply(self.mesh, data)

        vertices = cmds.ls(self.mesh + ".vtx[*]", flatten=True)
        extra_weights = [cmds.skinPercent(self.cluster, vertex, query=True, transform=extra) for vertex in vertices]
        self.assertTrue(all(abs(value) < 1.0e-8 for value in extra_weights))

    def test_subset_apply_only_changes_requested_vertices_and_undoes(self):
        data = skin_io.capture(self.mesh)
        vertices = cmds.ls(self.mesh + ".vtx[*]", flatten=True)
        for vertex in vertices:
            cmds.skinPercent(
                self.cluster,
                vertex,
                transformValue=((self.joint_a, 1.0), (self.joint_b, 0.0)),
            )
        modified = skin_io.capture(self.mesh)["weights"]

        skin_io.apply_subset(self.mesh, data, [0, 2])

        partial = skin_io.capture(self.mesh)["weights"]
        self.assertEqual(data["weights"][0], partial[0])
        self.assertEqual(modified[1], partial[1])
        self.assertEqual(data["weights"][2], partial[2])
        self.assertEqual(modified[3], partial[3])
        cmds.undo()
        self.assertEqual(modified, skin_io.capture(self.mesh)["weights"])

    def test_subset_zeros_extra_influence_only_on_requested_vertices(self):
        data = skin_io.capture(self.mesh)
        cmds.select(clear=True)
        extra = cmds.joint(name="extra_jnt", position=(0.0, 1.0, 0.0))
        cmds.skinCluster(self.cluster, edit=True, addInfluence=extra, weight=1.0)
        vertices = cmds.ls(self.mesh + ".vtx[*]", flatten=True)
        before = [cmds.skinPercent(self.cluster, vertex, query=True, transform=extra) for vertex in vertices]

        skin_io.apply_subset(self.mesh, data, [0])

        weights = [cmds.skinPercent(self.cluster, vertex, query=True, transform=extra) for vertex in vertices]
        self.assertAlmostEqual(0.0, weights[0])
        self.assertEqual(before[1:], weights[1:])

    def test_subset_invalid_indices_fail_before_edit(self):
        data = skin_io.capture(self.mesh)
        before = skin_io.capture(self.mesh)["weights"]

        with self.assertRaises(ValueError):
            skin_io.apply_subset(self.mesh, data, [0, 99])

        self.assertEqual(before, skin_io.capture(self.mesh)["weights"])

    def test_subset_requires_existing_skin_cluster(self):
        data = skin_io.capture(self.mesh)
        target = cmds.duplicate(self.mesh, name="unskinned_target")[0]
        cmds.delete(target, constructionHistory=True)

        with self.assertRaises(ValueError):
            skin_io.apply_subset(target, data, [0])

        target_shape = cmds.listRelatives(target, shapes=True, fullPath=True)[0]
        self.assertIsNone(skin_io._skin_cluster(target_shape))

    def test_selected_vertex_target_flattens_indices(self):
        cmds.select(self.mesh + ".vtx[0:1]", replace=True)

        shape, indices = skin_io._selected_vertex_target()

        self.assertEqual(skin_io._mesh_shape(self.mesh), shape)
        self.assertEqual([0, 1], indices)

    def test_selected_vertex_target_requires_one_mesh(self):
        second = cmds.polyPlane(name="cape")[0]
        cmds.select(self.mesh + ".vtx[0]", second + ".vtx[0]", replace=True)

        with self.assertRaises(ValueError):
            skin_io._selected_vertex_target()

    def test_same_vertex_count_with_changed_connectivity_is_rejected(self):
        data = skin_io.capture(self.mesh)
        data["mesh"]["topology"]["sha256"] = "0" * 64

        with self.assertRaises(ValueError):
            skin_io.apply(self.mesh, data)

    def test_invalid_weight_is_rejected_before_scene_edit(self):
        data = copy.deepcopy(skin_io.capture(self.mesh))
        data["weights"][0][0][1] = -1.0
        before = cmds.skinPercent(self.cluster, self.mesh + ".vtx[0]", query=True, value=True)

        with self.assertRaises(ValueError):
            skin_io.apply(self.mesh, data)

        after = cmds.skinPercent(self.cluster, self.mesh + ".vtx[0]", query=True, value=True)
        self.assertEqual(before, after)

    def test_missing_influence_is_rejected(self):
        data = skin_io.capture(self.mesh)
        cmds.delete(self.joint_b)

        with self.assertRaises(ValueError):
            skin_io.apply(self.mesh, data)

    def test_duplicate_resolved_influence_is_rejected_before_edit(self):
        """別レコードが同じscene jointへ解決されるJSONを拒否する。"""
        data = copy.deepcopy(skin_io.capture(self.mesh))
        first = data["influences"][0]
        data["influences"][1] = {
            "name": first["name"],
            "path": "|missing_alias_joint",
        }
        before = skin_io.capture(self.mesh)["weights"]

        with self.assertRaises(ValueError):
            skin_io.apply(self.mesh, data)

        self.assertEqual(before, skin_io.capture(self.mesh)["weights"])

    def test_transfer_to_different_topology_and_undo(self):
        data = skin_io.capture(self.mesh)
        target = cmds.polyPlane(name="retopo", subdivisionsX=2, subdivisionsY=1)[0]
        sentinel = cmds.spaceLocator(name="selection_sentinel")[0]
        cmds.select(sentinel, replace=True)

        cluster = skin_io.transfer(target, data)

        vertices = cmds.ls(target + ".vtx[*]", flatten=True)
        positions = [cmds.xform(vertex, query=True, worldSpace=True, translation=True)[0] for vertex in vertices]
        left = vertices[positions.index(min(positions))]
        right = vertices[positions.index(max(positions))]
        left_root = cmds.skinPercent(cluster, left, query=True, transform=self.joint_a)
        right_tip = cmds.skinPercent(cluster, right, query=True, transform=self.joint_b)
        self.assertGreater(left_root, 0.99)
        self.assertGreater(right_tip, 0.99)
        self.assertFalse(cmds.ls("__ywtaSkinTransferSource*", type="transform"))
        self.assertEqual([sentinel], cmds.ls(selection=True))

        cmds.undo()
        target_shape = cmds.listRelatives(target, shapes=True, fullPath=True)[0]
        self.assertIsNone(skin_io._skin_cluster(target_shape))

    def test_transfer_supports_closest_component(self):
        """Maya標準closestComponent方式を公開APIから利用できる。"""
        data = skin_io.capture(self.mesh)
        target = cmds.polyPlane(name="retopo", subdivisionsX=2, subdivisionsY=1)[0]

        cluster = skin_io.transfer(target, data, surface_association="closestComponent")

        self.assertTrue(cmds.objExists(cluster))
        self.assertEqual(6, len(skin_io.capture(target)["weights"]))

    def test_transfer_settings_and_options_window(self):
        """surface association設定を保存し、Options UIを構築できる。"""
        self.assertEqual("closestPoint", skin_io.get_transfer_settings())
        self.assertEqual("rayCast", skin_io.set_transfer_settings("rayCast"))
        self.assertEqual("rayCast", skin_io.get_transfer_settings())
        cmds.optionVar(stringValue=(skin_io.SURFACE_ASSOCIATION_OPTION, "invalid"))
        self.assertEqual("closestPoint", skin_io.get_transfer_settings())
        self.assertEqual("ywtaSkinTransferOptionsWindow", skin_io.show_transfer_options())

    def test_selected_transfer_uses_saved_surface_association(self):
        """メニュー入口が保存済み方式をload engineへ渡す。"""
        path = self.get_temp_filename("configured_transfer.json")
        skin_io.set_transfer_settings("rayCast")
        cmds.select(self.mesh, replace=True)

        with (
            mock.patch.object(skin_io.cmds, "fileDialog2", return_value=[path]),
            mock.patch.object(skin_io, "load_transfer", return_value="skinCluster") as load_transfer,
        ):
            result = skin_io.load_selected_transfer()

        self.assertEqual("skinCluster", result)
        load_transfer.assert_called_once_with("|" + self.mesh, path, surface_association="rayCast")

    def test_selected_transfer_preserves_explicit_invalid_association(self):
        """明示した不正値を保存設定へ暗黙fallbackしない。"""
        path = self.get_temp_filename("invalid_configured_transfer.json")
        cmds.select(self.mesh, replace=True)

        with (
            mock.patch.object(skin_io.cmds, "fileDialog2", return_value=[path]),
            mock.patch.object(skin_io, "load_transfer", return_value="sentinel") as load_transfer,
        ):
            skin_io.load_selected_transfer(surface_association="")

        load_transfer.assert_called_once_with("|" + self.mesh, path, surface_association="")

    def test_transfer_requires_saved_geometry_before_edit(self):
        data = skin_io.capture(self.mesh)
        del data["mesh"]["geometry"]
        target = cmds.polyPlane(name="retopo", subdivisionsX=2)[0]

        with self.assertRaises(ValueError):
            skin_io.transfer(target, data)

        target_shape = cmds.listRelatives(target, shapes=True, fullPath=True)[0]
        self.assertIsNone(skin_io._skin_cluster(target_shape))

    def test_transfer_rejects_unknown_association_before_edit(self):
        """不正なsurface associationでtargetへskinClusterを作らない。"""
        data = skin_io.capture(self.mesh)
        target = cmds.polyPlane(name="retopo", subdivisionsX=2)[0]

        with self.assertRaises(ValueError):
            skin_io.transfer(target, data, surface_association="")

        target_shape = cmds.listRelatives(target, shapes=True, fullPath=True)[0]
        self.assertIsNone(skin_io._skin_cluster(target_shape))

    def test_transfer_rejects_scene_convention_mismatch_before_edit(self):
        data = skin_io.capture(self.mesh)
        data["scene"]["linear_unit"] = "m" if cmds.currentUnit(query=True, linear=True) != "m" else "cm"
        target = cmds.polyPlane(name="retopo", subdivisionsX=2)[0]

        with self.assertRaises(ValueError):
            skin_io.transfer(target, data)

        target_shape = cmds.listRelatives(target, shapes=True, fullPath=True)[0]
        self.assertIsNone(skin_io._skin_cluster(target_shape))

    def test_transfer_locked_influence_rolls_back_new_target_cluster(self):
        """locked拒否時にtarget clusterや一時source meshを残さない。"""
        data = skin_io.capture(self.mesh)
        target = cmds.polyPlane(name="retopo", subdivisionsX=2)[0]
        cmds.setAttr(self.joint_a + ".lockInfluenceWeights", True)

        with self.assertRaises(ValueError):
            skin_io.transfer(target, data)

        target_shape = cmds.listRelatives(target, shapes=True, fullPath=True)[0]
        self.assertIsNone(skin_io._skin_cluster(target_shape))
        self.assertFalse(cmds.ls("__ywtaSkinTransferSource*", type="transform"))

    def test_transfer_zeros_existing_extra_influence(self):
        data = skin_io.capture(self.mesh)
        target = cmds.polyPlane(name="retopo", subdivisionsX=2)[0]
        cmds.select(clear=True)
        extra = cmds.joint(name="extra_jnt", position=(0.0, 1.0, 0.0))
        cluster = cmds.skinCluster(extra, target, toSelectedBones=True, normalizeWeights=1)[0]

        skin_io.transfer(target, data)

        vertices = cmds.ls(target + ".vtx[*]", flatten=True)
        extra_weights = [cmds.skinPercent(cluster, vertex, query=True, transform=extra) for vertex in vertices]
        self.assertTrue(all(abs(value) < 1.0e-8 for value in extra_weights))

        cmds.undo()
        self.assertEqual([extra], cmds.skinCluster(cluster, query=True, influence=True))
        restored_extra = [cmds.skinPercent(cluster, vertex, query=True, transform=extra) for vertex in vertices]
        self.assertTrue(all(abs(value - 1.0) < 1.0e-8 for value in restored_extra))

        cmds.redo()
        redone_extra = [cmds.skinPercent(cluster, vertex, query=True, transform=extra) for vertex in vertices]
        self.assertTrue(all(abs(value) < 1.0e-8 for value in redone_extra))
