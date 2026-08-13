"""DCC非依存RBF solverを検証する。"""

import unittest

import numpy as np

from ywta.rig.rbf_solver import CancelledError, RbfSolver, sample_spatial_indices


class RbfSolverTests(unittest.TestCase):
    """Sampling、weight共有、進捗、キャンセルを検証する。"""

    def setUp(self):
        rng = np.random.default_rng(42)
        self.source = rng.random((32, 3))
        self.target = self.source * np.array([1.2, 0.8, 1.1]) + np.array([2.0, -1.0, 0.5])

    def test_spatial_sampling_is_deterministic_and_distributed(self):
        first = sample_spatial_indices(self.source, 8)
        second = sample_spatial_indices(self.source, 8)
        np.testing.assert_array_equal(first, second)
        self.assertEqual(8, len(np.unique(first)))
        self.assertTrue(np.all(first[:-1] < first[1:]))

    def test_fit_samples_controls_and_reuses_weights(self):
        solver = RbfSolver.fit(self.source, self.target, max_control_points=12)
        point_sets = [self.source[:5], self.source[5:11]]
        results = solver.transform_many(point_sets)

        self.assertEqual((12, 3), solver.source.shape)
        self.assertEqual((16, 3), solver.weights.shape)
        for points, result in zip(point_sets, results):
            expected = points * np.array([1.2, 0.8, 1.1]) + np.array([2.0, -1.0, 0.5])
            np.testing.assert_allclose(result, expected, atol=2e-14)

    def test_progress_reports_fit_and_each_follower(self):
        events = []
        solver = RbfSolver.fit(
            self.source,
            self.target,
            max_control_points=12,
            progress=lambda *event: events.append(event),
        )
        solver.transform_many(
            [self.source[:2], self.source[2:4]],
            progress=lambda *event: events.append(event),
        )
        self.assertEqual(
            [
                ("sampling", 0, 1),
                ("sampling", 1, 1),
                ("solving", 0, 1),
                ("solving", 1, 1),
                ("deforming", 0, 2),
                ("deforming", 1, 2),
                ("deforming", 2, 2),
            ],
            events,
        )

    def test_cancel_before_solve(self):
        with self.assertRaises(CancelledError):
            RbfSolver.fit(self.source, self.target, cancelled=lambda: True)

    def test_cancel_between_followers(self):
        solver = RbfSolver.fit(self.source, self.target, max_control_points=12)
        checks = iter((False, False, True))
        with self.assertRaises(CancelledError):
            solver.transform_many(
                [self.source[:2], self.source[2:4]],
                cancelled=lambda: next(checks),
            )

    def test_sampling_rejects_too_few_controls(self):
        with self.assertRaisesRegex(ValueError, "at least 4"):
            sample_spatial_indices(self.source, 3)


if __name__ == "__main__":
    unittest.main()
