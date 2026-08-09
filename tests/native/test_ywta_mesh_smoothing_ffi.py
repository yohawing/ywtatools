"""ビルド済みRust DLLのC ABIを検証する最小ネイティブスモーク。"""

from __future__ import annotations

import ctypes
import math
import os
from pathlib import Path
import unittest


ABI_VERSION = 1
MODE_UNIFORM_LAPLACIAN = 0
MODE_TAUBIN = 1
CONSTRAINT_FIXED = 1
CONSTRAINT_RAIL_LINE = 3
STATUS_OK = 0
STATUS_ABI_MISMATCH = 2
STATUS_NULL_POINTER = 3
STATUS_OUTPUT_TOO_SMALL = 5
STATUS_EDGE_INDEX_OUT_OF_RANGE = 6
STATUS_NON_FINITE = 7


class Options(ctypes.Structure):
    _fields_ = [
        ("abi_version", ctypes.c_uint32),
        ("struct_size", ctypes.c_uint32),
        ("mode", ctypes.c_uint32),
        ("iterations", ctypes.c_uint32),
        ("strength", ctypes.c_double),
        ("taubin_mu", ctypes.c_double),
    ]


class LegacyOptionsV1(ctypes.Structure):
    _fields_ = Options._fields_[:-1]


class Request(ctypes.Structure):
    _fields_ = [
        ("abi_version", ctypes.c_uint32),
        ("struct_size", ctypes.c_uint32),
        ("positions", ctypes.POINTER(ctypes.c_double)),
        ("position_count", ctypes.c_uint64),
        ("edges", ctypes.POINTER(ctypes.c_uint32)),
        ("edge_count", ctypes.c_uint64),
        ("output", ctypes.POINTER(ctypes.c_double)),
        ("output_len", ctypes.c_uint64),
        ("options", ctypes.POINTER(Options)),
        ("vertex_weights", ctypes.POINTER(ctypes.c_double)),
        ("constraint_modes", ctypes.POINTER(ctypes.c_uint32)),
        ("constraint_directions", ctypes.POINTER(ctypes.c_double)),
    ]


class LegacyRequestV1(ctypes.Structure):
    _fields_ = Request._fields_[:-3]


def _dll_path() -> Path:
    configured = os.environ.get("YWTA_MESH_SMOOTHING_DLL")
    if configured:
        return Path(configured)
    return Path(__file__).parents[2] / "bin" / "windows" / "ywta_mesh_smoothing.dll"


def _load_library() -> ctypes.CDLL:
    library = ctypes.CDLL(str(_dll_path()))
    library.ywta_mesh_smoothing_apply.argtypes = [ctypes.POINTER(Request)]
    library.ywta_mesh_smoothing_apply.restype = ctypes.c_int32
    return library


class MeshSmoothingFfiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.library = _load_library()

    @staticmethod
    def _options(mode=MODE_UNIFORM_LAPLACIAN) -> Options:
        return Options(
            ABI_VERSION,
            ctypes.sizeof(Options),
            mode,
            1,
            0.3,
            -0.34,
        )

    def _request(self, positions, edges, output, options) -> Request:
        position_pointer = ctypes.cast(positions, ctypes.POINTER(ctypes.c_double)) if positions else None
        edge_pointer = ctypes.cast(edges, ctypes.POINTER(ctypes.c_uint32)) if edges else None
        output_pointer = ctypes.cast(output, ctypes.POINTER(ctypes.c_double)) if output else None
        return Request(
            ABI_VERSION,
            ctypes.sizeof(Request),
            position_pointer,
            len(positions) // 3 if positions else 1,
            edge_pointer,
            len(edges) // 2 if edges else 0,
            output_pointer,
            len(output) if output else 0,
            ctypes.pointer(options),
            None,
            None,
            None,
        )

    def test_success_and_rejected_inputs(self) -> None:
        positions = (ctypes.c_double * 6)(0.0, 0.0, 0.0, 2.0, 0.0, 0.0)
        edges = (ctypes.c_uint32 * 2)(0, 1)
        output = (ctypes.c_double * 6)()
        options = self._options()
        request = self._request(positions, edges, output, options)

        self.assertEqual(self.library.ywta_mesh_smoothing_apply(ctypes.byref(request)), STATUS_OK)
        self.assertEqual(list(output), [0.6, 0.0, 0.0, 1.4, 0.0, 0.0])

        request.abi_version = ABI_VERSION + 1
        self.assertEqual(
            self.library.ywta_mesh_smoothing_apply(ctypes.byref(request)),
            STATUS_ABI_MISMATCH,
        )
        request.abi_version = ABI_VERSION

        request.positions = None
        request.position_count = 1
        self.assertEqual(
            self.library.ywta_mesh_smoothing_apply(ctypes.byref(request)),
            STATUS_NULL_POINTER,
        )
        request.positions = ctypes.cast(positions, ctypes.POINTER(ctypes.c_double))
        request.position_count = 2

        request.output_len = 5
        self.assertEqual(
            self.library.ywta_mesh_smoothing_apply(ctypes.byref(request)),
            STATUS_OUTPUT_TOO_SMALL,
        )
        request.output_len = 6

        edges[1] = 2
        self.assertEqual(
            self.library.ywta_mesh_smoothing_apply(ctypes.byref(request)),
            STATUS_EDGE_INDEX_OUT_OF_RANGE,
        )
        edges[1] = 1

        positions[0] = math.nan
        self.assertEqual(
            self.library.ywta_mesh_smoothing_apply(ctypes.byref(request)),
            STATUS_NON_FINITE,
        )

    def test_taubin_and_legacy_uniform_options(self) -> None:
        self.assertEqual(ctypes.sizeof(LegacyOptionsV1), 24)
        self.assertEqual(ctypes.sizeof(Options), 32)
        self.assertEqual(ctypes.sizeof(LegacyRequestV1), 64)
        self.assertEqual(ctypes.sizeof(Request), 88)

        positions = (ctypes.c_double * 6)(0.0, 0.0, 0.0, 2.0, 0.0, 0.0)
        edges = (ctypes.c_uint32 * 2)(0, 1)
        output = (ctypes.c_double * 6)()

        taubin_options = self._options(MODE_TAUBIN)
        request = self._request(positions, edges, output, taubin_options)
        self.assertEqual(self.library.ywta_mesh_smoothing_apply(ctypes.byref(request)), STATUS_OK)
        self.assertAlmostEqual(output[0], 0.328)
        self.assertAlmostEqual(output[3], 1.672)

        legacy_options = LegacyOptionsV1(
            ABI_VERSION,
            ctypes.sizeof(LegacyOptionsV1),
            MODE_UNIFORM_LAPLACIAN,
            1,
            0.3,
        )
        request.options = ctypes.cast(ctypes.pointer(legacy_options), ctypes.POINTER(Options))
        self.assertEqual(self.library.ywta_mesh_smoothing_apply(ctypes.byref(request)), STATUS_OK)
        self.assertAlmostEqual(output[0], 0.6)
        self.assertAlmostEqual(output[3], 1.4)

        legacy_request = LegacyRequestV1(*[getattr(request, name) for name, _ in LegacyRequestV1._fields_])
        legacy_request.struct_size = ctypes.sizeof(LegacyRequestV1)
        legacy_request.options = ctypes.cast(ctypes.pointer(legacy_options), ctypes.POINTER(Options))
        self.assertEqual(
            self.library.ywta_mesh_smoothing_apply(
                ctypes.cast(ctypes.pointer(legacy_request), ctypes.POINTER(Request))
            ),
            STATUS_OK,
        )

        constrained_positions = (ctypes.c_double * 6)(0.0, 0.0, 0.0, 2.0, 2.0, 0.0)
        weights = (ctypes.c_double * 2)(0.5, 1.0)
        modes = (ctypes.c_uint32 * 2)(CONSTRAINT_RAIL_LINE, CONSTRAINT_FIXED)
        directions = (ctypes.c_double * 6)(1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        current_options = self._options()
        request = self._request(constrained_positions, edges, output, current_options)
        request.vertex_weights = weights
        request.constraint_modes = modes
        request.constraint_directions = directions
        self.assertEqual(self.library.ywta_mesh_smoothing_apply(ctypes.byref(request)), STATUS_OK)
        self.assertAlmostEqual(output[0], 0.3)
        self.assertAlmostEqual(output[1], 0.0)
        self.assertAlmostEqual(output[3], 2.0)
        self.assertAlmostEqual(output[4], 2.0)


if __name__ == "__main__":
    unittest.main()
