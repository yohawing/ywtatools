"""RustメッシュスムージングDLLのctypesバインディングを検証する。"""

import ctypes
import os
import sys
import unittest


_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", "..", ".."))
_MODULES_DIR = os.path.join(_REPO_ROOT, "blender", "modules")
if _MODULES_DIR not in sys.path:
    sys.path.insert(0, _MODULES_DIR)

from ywta_mesh_smoothing import binding  # noqa: E402


class FakeSmoothingDLL:
    """要求を記録し、入力位置へ1を加えた出力を書く偽DLL。"""

    def __init__(self, status=0):
        self.status = status
        self.request = None

    def ywta_mesh_smoothing_apply(self, request_pointer):
        request = request_pointer.contents

        def read(pointer, count):
            return list(pointer[:count]) if pointer else []

        self.request = {
            "positions": read(request.positions, request.position_count * 3),
            "edges": read(request.edges, request.edge_count * 2),
            "triangles": read(request.triangles, request.triangle_count * 3),
            "options": request.options.contents,
            "weights": read(request.vertex_weights, request.position_count),
            "modes": read(request.constraint_modes, request.position_count),
            "directions": read(request.constraint_directions, request.position_count * 3),
        }
        if self.status == 0:
            for index, value in enumerate(self.request["positions"]):
                request.output[index] = value + 1.0
        return self.status


class MeshSmoothingBindingTests(unittest.TestCase):
    def setUp(self):
        self.original_loader = binding._load_dll

    def tearDown(self):
        binding._load_dll = self.original_loader
        binding.reset_dll_cache()

    def test_layout_and_default_path(self):
        self.assertEqual(ctypes.sizeof(binding.MeshSmoothingOptions), 56)
        self.assertEqual(ctypes.sizeof(binding.MeshSmoothingRequest), 104)
        self.assertTrue(
            str(binding.default_dll_path())
            .replace("\\", "/")
            .endswith("bin/windows/ywta_mesh_smoothing.dll")
        )

    def test_marshals_all_optional_inputs_and_copies_output(self):
        fake = FakeSmoothingDLL()
        binding._load_dll = lambda: fake
        result = binding.smooth(
            [0.0, 0.0, 0.0, 2.0, 0.0, 0.0],
            [0, 1],
            mode=binding.MODE_HC,
            iterations=3,
            triangles=[0, 1, 0],
            vertex_weights=[0.5, 1.0],
            constraint_modes=[binding.CONSTRAINT_NORMAL_ONLY, binding.CONSTRAINT_FIXED],
            constraint_directions=[0.0, 1.0, 0.0, 1.0, 0.0, 0.0],
        )

        self.assertEqual(result, [1.0, 1.0, 1.0, 3.0, 1.0, 1.0])
        self.assertEqual(fake.request["edges"], [0, 1])
        self.assertEqual(fake.request["triangles"], [0, 1, 0])
        self.assertEqual(fake.request["weights"], [0.5, 1.0])
        self.assertEqual(fake.request["modes"], [binding.CONSTRAINT_NORMAL_ONLY, binding.CONSTRAINT_FIXED])
        self.assertEqual(fake.request["options"].iterations, 3)

    def test_rejects_invalid_python_inputs_before_ffi(self):
        binding._load_dll = lambda: self.fail("不正入力でDLLを呼んではならない")
        with self.assertRaises(ValueError):
            binding.smooth([0.0, 0.0], [])
        with self.assertRaises(ValueError):
            binding.smooth([0.0, 0.0, 0.0], [0, 1])
        with self.assertRaises(ValueError):
            binding.smooth(
                [0.0, 0.0, 0.0],
                [],
                constraint_modes=[binding.CONSTRAINT_NORMAL_ONLY],
            )

    def test_nonzero_status_raises_typed_error(self):
        binding._load_dll = lambda: FakeSmoothingDLL(status=12)
        with self.assertRaises(binding.MeshSmoothingError) as context:
            binding.smooth([0.0, 0.0, 0.0], [])
        self.assertEqual(context.exception.status, 12)


if __name__ == "__main__":
    unittest.main()
