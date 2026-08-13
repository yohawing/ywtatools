"""Mesh RetargetのRBF数値契約を検証する。"""

import sys
import types
import unittest
from unittest import mock

import numpy as np


try:
    import maya  # noqa: F401
except ImportError:
    maya_module = types.ModuleType("maya")
    api_module = types.ModuleType("maya.api")
    open_maya_module = types.ModuleType("maya.api.OpenMaya")
    cmds_module = types.ModuleType("maya.cmds")
    maya_module.api = api_module
    api_module.OpenMaya = open_maya_module
    shortcuts_module = types.ModuleType("ywta.shortcuts")
    sys.modules.update(
        {
            "maya": maya_module,
            "maya.api": api_module,
            "maya.api.OpenMaya": open_maya_module,
            "maya.cmds": cmds_module,
            "ywta.shortcuts": shortcuts_module,
        }
    )

from ywta.rig import meshretarget


class RbfCharacterizationTests(unittest.TestCase):
    """既存RBF solverの精度と失敗条件を固定する。"""

    def setUp(self):
        self.source = np.array(
            [
                [0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [0.0, 0.0, 1.0],
                [1.0, 1.0, 1.0],
            ]
        )
        self.affine = np.array([[1.2, 0.1, 0.0], [0.0, 0.8, 0.2], [0.1, 0.0, 1.1]])
        self.offset = np.array([2.0, -1.0, 0.5])
        self.target = self.source @ self.affine + self.offset

    def test_all_kernels_reproduce_affine_transform(self):
        samples = np.array([[0.2, 0.3, 0.1], [0.4, 0.1, 0.2]])
        expected = samples @ self.affine + self.offset
        kernels = (
            meshretarget.RBF.linear,
            meshretarget.RBF.gaussian,
            meshretarget.RBF.thin_plate,
            meshretarget.RBF.multi_quadratic_biharmonic,
            meshretarget.RBF.inv_multi_quadratic_biharmonic,
            meshretarget.RBF.beckert_wendland_c2_basis,
        )

        for kernel in kernels:
            with self.subTest(kernel=kernel.__name__):
                weights = meshretarget.get_weight_matrix(self.source, self.target, kernel, 0.5)
                distances = meshretarget.get_distance_matrix(samples, self.source, kernel, 0.5)
                basis = np.block([distances, np.ones((2, 1)), samples])
                actual = np.asarray(basis @ weights)
                np.testing.assert_allclose(actual, expected, atol=2e-15)

    def test_weight_matrix_has_control_points_plus_affine_rows(self):
        weights = meshretarget.get_weight_matrix(self.source, self.target, meshretarget.RBF.linear, 0.5)
        self.assertEqual((self.source.shape[0] + 4, 3), weights.shape)

    def test_mismatched_control_point_counts_fail(self):
        with self.assertRaises(ValueError):
            meshretarget.get_weight_matrix(
                self.source,
                self.target[:-1],
                meshretarget.RBF.linear,
                0.5,
            )

    def test_duplicate_control_points_fail_as_singular(self):
        duplicate_source = self.source.copy()
        duplicate_source[-1] = duplicate_source[0]
        with self.assertRaises(np.linalg.LinAlgError):
            meshretarget.get_weight_matrix(
                duplicate_source,
                self.target,
                meshretarget.RBF.linear,
                0.5,
            )

    def test_coplanar_control_points_fail_as_singular(self):
        coplanar_source = self.source.copy()
        coplanar_source[:, 2] = 0.0
        with self.assertRaises(np.linalg.LinAlgError):
            meshretarget.get_weight_matrix(
                coplanar_source,
                self.target,
                meshretarget.RBF.linear,
                0.5,
            )

    def test_maya_adapter_uses_spatial_solver_for_multiple_followers(self):
        follower_a = np.array([[0.2, 0.3, 0.1], [0.4, 0.1, 0.2]])
        follower_b = np.array([[0.3, 0.2, 0.4]])
        point_sets = {
            "source": self.source,
            "target": self.target,
            "follower_a": follower_a,
            "follower_b": follower_b,
        }

        with (
            mock.patch.object(
                meshretarget,
                "points_to_np_array",
                side_effect=lambda name, stride=1: point_sets[name][::stride],
            ),
            mock.patch.object(
                meshretarget.OpenMaya,
                "MPoint",
                side_effect=lambda *values: tuple(values),
                create=True,
            ),
            mock.patch.object(
                meshretarget.cmds,
                "duplicate",
                side_effect=lambda object_name, **_kwargs: [object_name + "_copy"],
                create=True,
            ),
            mock.patch.object(meshretarget, "set_points") as set_points,
        ):
            meshretarget.retarget(
                "source",
                "target",
                ["follower_a", "follower_b"],
                max_control_points=5,
            )

        self.assertEqual(2, set_points.call_count)
        for call, original in zip(set_points.call_args_list, (follower_a, follower_b)):
            self.assertTrue(call.args[0].endswith("_copy"))
            expected = original @ self.affine + self.offset
            np.testing.assert_allclose(np.asarray(call.args[1]), expected, atol=2e-14)


if __name__ == "__main__":
    unittest.main()
