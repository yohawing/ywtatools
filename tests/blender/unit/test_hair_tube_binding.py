"""Hair Tube ctypesバインディングをBlenderなしで検証する。"""

import ctypes
import os
import sys
import unittest


_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_MODULES_DIR = os.path.join(_REPO_ROOT, "blender", "modules")
if _MODULES_DIR not in sys.path:
    sys.path.insert(0, _MODULES_DIR)

from ywta_mesh_core import hair_tube  # noqa: E402


class FakeDLL:
    """入力を記録し、最小の成功結果またはエラーを返す偽DLL。"""

    def __init__(self, status=0):
        self.status = status
        self.freed = False
        self.input = None
        self._owned = []

    def ywta_hair_tube_generate(
        self,
        vertex_count,
        positions,
        offsets,
        face_count,
        faces,
        corner_count,
        root,
        segments,
        tolerance,
        output_pointer,
    ):
        self.input = {
            "vertex_count": vertex_count,
            "positions": list(positions[: vertex_count * 3]),
            "offsets": list(offsets[: face_count + 1]),
            "faces": list(faces[:corner_count]),
            "root": list(root[:4]),
            "segments": segments,
            "tolerance": tolerance,
        }
        if self.status:
            return self.status
        output = output_pointer.contents
        position_values = (ctypes.c_double * 12)(*([0.0] * 12))
        quad_values = (ctypes.c_uint32 * 4)(0, 1, 2, 3)
        interval_values = (ctypes.c_uint64 * 4)(0, 0, 0, 0)
        alpha_values = (ctypes.c_double * 4)(0.0, 0.0, 0.0, 0.0)
        source_vertex_values = (ctypes.c_uint32 * 8)(0, 4, 1, 5, 2, 6, 3, 7)
        source_face_values = (ctypes.c_uint64 * 1)(3)
        source_corner_face_values = (ctypes.c_uint64 * 4)(3, 3, 3, 3)
        self._owned = [
            position_values,
            quad_values,
            interval_values,
            alpha_values,
            source_vertex_values,
            source_face_values,
            source_corner_face_values,
        ]
        output.vertex_count = 4
        output.quad_count = 1
        output.positions_xyz = position_values
        output.quad_indices = quad_values
        output.source_intervals = interval_values
        output.source_alphas = alpha_values
        output.source_vertex_pairs = source_vertex_values
        output.source_faces = source_face_values
        output.source_corner_faces = source_corner_face_values
        output.source_station_count = 2
        output.max_fit_deviation = 0.25
        output.max_source_distance = 0.5
        output.cubic_active = 1
        return 0

    def ywta_hair_tube_free(self, _output_pointer):
        self.freed = True

    def ywta_hair_tube_generate_from_rails(self, rails, station_count, segments, tolerance, output_pointer):
        self.input = {
            "rails": list(rails[: station_count * 4 * 3]),
            "station_count": station_count,
            "segments": segments,
            "tolerance": tolerance,
        }
        if self.status:
            return self.status
        return self.ywta_hair_tube_generate(
            4,
            (ctypes.c_double * 12)(*([0.0] * 12)),
            (ctypes.c_uint64 * 1)(0),
            0,
            (ctypes.c_uint32 * 0)(),
            0,
            (ctypes.c_uint32 * 4)(0, 1, 2, 3),
            segments,
            tolerance,
            output_pointer,
        )

    def ywta_mesh_core_last_error(self):
        return b"fake diagnostic"


class HairTubeBindingTests(unittest.TestCase):
    def setUp(self):
        self.original_loader = hair_tube._load_dll

    def tearDown(self):
        hair_tube._load_dll = self.original_loader
        hair_tube.reset_dll_cache()

    def test_marshals_input_copies_output_and_frees(self):
        fake = FakeDLL()
        hair_tube._load_dll = lambda: fake
        result = hair_tube.generate(
            [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)],
            [(0, 1, 2, 3)],
            (0, 1, 2, 3),
            target_segments=3,
            fit_tolerance=0.1,
        )
        self.assertEqual(fake.input["offsets"], [0, 4])
        self.assertEqual(fake.input["root"], [0, 1, 2, 3])
        self.assertEqual(fake.input["segments"], 3)
        self.assertEqual(result.quads, [(0, 1, 2, 3)])
        self.assertEqual(result.source_station_count, 2)
        self.assertEqual(result.source_vertex_pairs[0], (0, 4))
        self.assertEqual(result.source_faces, [3])
        self.assertEqual(result.source_corner_faces, [3, 3, 3, 3])
        self.assertTrue(result.cubic_active)
        self.assertTrue(fake.freed)

    def test_rejects_invalid_python_input_before_ffi(self):
        hair_tube._load_dll = lambda: self.fail("不正入力でDLLを呼んではならない")
        with self.assertRaises(ValueError):
            hair_tube.generate([(0, 0, 0)], [], (0, 0, 0, 0))
        with self.assertRaises(ValueError):
            hair_tube.generate([(0, 0, float("nan"))] * 4, [], (0, 1, 2, 3))
        with self.assertRaises(ValueError):
            hair_tube.generate([(0, 0, 0)] * 4, [], (0, 1, 2, 3), target_segments=0)

    def test_nonzero_status_raises_diagnostic(self):
        fake = FakeDLL(status=105)
        hair_tube._load_dll = lambda: fake
        with self.assertRaises(hair_tube.HairTubeError) as context:
            hair_tube.generate([(0, 0, 0)] * 4, [], (0, 1, 2, 3))
        self.assertEqual(context.exception.status, 105)
        self.assertIn("fake diagnostic", str(context.exception))
        self.assertFalse(fake.freed)

    def test_generate_from_edited_rails(self):
        fake = FakeDLL()
        hair_tube._load_dll = lambda: fake
        rails = [[(rail, 0, 0), (rail, 0, 1)] for rail in range(4)]
        result = hair_tube.generate_from_rails(rails, target_segments=5)
        self.assertEqual(fake.input["segments"], 5)
        self.assertEqual(result.quads, [(0, 1, 2, 3)])
        self.assertTrue(fake.freed)

    def test_default_path_targets_shared_core_dll(self):
        self.assertTrue(str(hair_tube.default_dll_path()).replace("\\", "/").endswith("bin/windows/ywta_mesh_core.dll"))


if __name__ == "__main__":
    unittest.main()
