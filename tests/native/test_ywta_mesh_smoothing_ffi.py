"""ビルド済みRust DLLのC ABIを検証する最小ネイティブスモーク。"""

from __future__ import annotations

import ctypes
import math
import os
from pathlib import Path
import sys
import unittest


ABI_VERSION = 1
MODE_UNIFORM_LAPLACIAN = 0
MODE_TAUBIN = 1
MODE_HC = 2
CONSTRAINT_FIXED = 1
CONSTRAINT_RAIL_LINE = 3
STATUS_OK = 0
STATUS_ABI_MISMATCH = 2
STATUS_NULL_POINTER = 3
STATUS_OUTPUT_TOO_SMALL = 5
STATUS_EDGE_INDEX_OUT_OF_RANGE = 6
STATUS_NON_FINITE = 7
STATUS_INVALID_TOPOLOGY = 12

_REPO_ROOT = Path(__file__).parents[2]
_BLENDER_MODULES = _REPO_ROOT / "blender" / "modules"
if str(_BLENDER_MODULES) not in sys.path:
    sys.path.insert(0, str(_BLENDER_MODULES))

from ywta_mesh_smoothing import binding as blender_binding  # noqa: E402


class Options(ctypes.Structure):
    _fields_ = [
        ("abi_version", ctypes.c_uint32),
        ("struct_size", ctypes.c_uint32),
        ("mode", ctypes.c_uint32),
        ("iterations", ctypes.c_uint32),
        ("strength", ctypes.c_double),
        ("taubin_mu", ctypes.c_double),
        ("hc_alpha", ctypes.c_double),
        ("hc_beta", ctypes.c_double),
        ("volume_correction", ctypes.c_double),
    ]


class LegacyOptionsV1(ctypes.Structure):
    _fields_ = Options._fields_[:5]


class TaubinOptionsV2(ctypes.Structure):
    _fields_ = Options._fields_[:6]


class HcOptionsV3(ctypes.Structure):
    _fields_ = Options._fields_[:8]


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
        ("triangles", ctypes.POINTER(ctypes.c_uint32)),
        ("triangle_count", ctypes.c_uint64),
    ]


class LegacyRequestV1(ctypes.Structure):
    _fields_ = Request._fields_[:9]


class ConstraintRequestV2(ctypes.Structure):
    _fields_ = Request._fields_[:12]


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


def _signed_volume(positions: list[float], triangles: list[int]) -> float:
    """Rust実装から独立したスカラー三重積で符号付き体積を測る。"""
    volume = 0.0
    for offset in range(0, len(triangles), 3):
        a_index, b_index, c_index = triangles[offset : offset + 3]
        ax, ay, az = positions[a_index * 3 : a_index * 3 + 3]
        bx, by, bz = positions[b_index * 3 : b_index * 3 + 3]
        cx, cy, cz = positions[c_index * 3 : c_index * 3 + 3]
        volume += (
            ax * (by * cz - bz * cy)
            + ay * (bz * cx - bx * cz)
            + az * (bx * cy - by * cx)
        ) / 6.0
    return volume


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
            0.0,
            0.5,
            0.0,
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
            None,
            0,
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
        self.assertEqual(ctypes.sizeof(TaubinOptionsV2), 32)
        self.assertEqual(ctypes.sizeof(HcOptionsV3), 48)
        self.assertEqual(ctypes.sizeof(Options), 56)
        self.assertEqual(ctypes.sizeof(LegacyRequestV1), 64)
        self.assertEqual(ctypes.sizeof(ConstraintRequestV2), 88)
        self.assertEqual(ctypes.sizeof(Request), 104)

        positions = (ctypes.c_double * 6)(0.0, 0.0, 0.0, 2.0, 0.0, 0.0)
        edges = (ctypes.c_uint32 * 2)(0, 1)
        output = (ctypes.c_double * 6)()

        taubin_options = self._options(MODE_TAUBIN)
        request = self._request(positions, edges, output, taubin_options)
        self.assertEqual(self.library.ywta_mesh_smoothing_apply(ctypes.byref(request)), STATUS_OK)
        self.assertAlmostEqual(output[0], 0.328)
        self.assertAlmostEqual(output[3], 1.672)

        hc_options = self._options(MODE_HC)
        request = self._request(positions, edges, output, hc_options)
        self.assertEqual(self.library.ywta_mesh_smoothing_apply(ctypes.byref(request)), STATUS_OK)
        self.assertAlmostEqual(output[0], 0.6)
        self.assertAlmostEqual(output[3], 1.4)

        legacy_hc_options = HcOptionsV3(
            ABI_VERSION,
            ctypes.sizeof(HcOptionsV3),
            MODE_HC,
            1,
            0.3,
            -0.34,
            0.0,
            0.5,
        )
        request.options = ctypes.cast(ctypes.pointer(legacy_hc_options), ctypes.POINTER(Options))
        self.assertEqual(self.library.ywta_mesh_smoothing_apply(ctypes.byref(request)), STATUS_OK)

        short_hc_options = TaubinOptionsV2(
            ABI_VERSION,
            ctypes.sizeof(TaubinOptionsV2),
            MODE_HC,
            1,
            0.3,
            -0.34,
        )
        request.options = ctypes.cast(ctypes.pointer(short_hc_options), ctypes.POINTER(Options))
        self.assertEqual(
            self.library.ywta_mesh_smoothing_apply(ctypes.byref(request)),
            STATUS_ABI_MISMATCH,
        )

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

        constraint_request = ConstraintRequestV2(
            *[getattr(request, name) for name, _ in ConstraintRequestV2._fields_]
        )
        constraint_request.struct_size = ctypes.sizeof(ConstraintRequestV2)
        self.assertEqual(
            self.library.ywta_mesh_smoothing_apply(
                ctypes.cast(ctypes.pointer(constraint_request), ctypes.POINTER(Request))
            ),
            STATUS_OK,
        )
        self.assertAlmostEqual(output[0], 0.3)
        self.assertAlmostEqual(output[1], 0.0)

    def test_signed_volume_correction_and_open_mesh_rejection(self) -> None:
        positions = (ctypes.c_double * 18)(
            1.0,
            0.0,
            0.0,
            -1.0,
            0.0,
            0.0,
            0.0,
            1.0,
            0.0,
            0.0,
            -1.0,
            0.0,
            0.0,
            0.0,
            1.0,
            0.0,
            0.0,
            -1.0,
        )
        edges = (ctypes.c_uint32 * 24)(
            0, 2, 0, 3, 0, 4, 0, 5, 1, 2, 1, 3, 1, 4, 1, 5, 2, 4, 2, 5, 3, 4, 3, 5
        )
        triangle_values = [
            4, 0, 2, 4, 2, 1, 4, 1, 3, 4, 3, 0, 5, 2, 0, 5, 1, 2, 5, 3, 1, 5, 0, 3
        ]
        triangles = (ctypes.c_uint32 * len(triangle_values))(*triangle_values)
        output = (ctypes.c_double * 18)()
        options = self._options()
        options.volume_correction = 1.0
        request = self._request(positions, edges, output, options)
        request.triangles = triangles
        request.triangle_count = len(triangle_values) // 3

        self.assertEqual(self.library.ywta_mesh_smoothing_apply(ctypes.byref(request)), STATUS_OK)
        self.assertAlmostEqual(
            _signed_volume(list(output), triangle_values),
            _signed_volume(list(positions), triangle_values),
            places=9,
        )

        request.triangle_count = 1
        self.assertEqual(
            self.library.ywta_mesh_smoothing_apply(ctypes.byref(request)),
            STATUS_INVALID_TOPOLOGY,
        )

        request.triangles = None
        request.triangle_count = len(triangle_values) // 3
        self.assertEqual(
            self.library.ywta_mesh_smoothing_apply(ctypes.byref(request)),
            STATUS_NULL_POINTER,
        )

        request.triangles = triangles
        short_request = ConstraintRequestV2(
            *[getattr(request, name) for name, _ in ConstraintRequestV2._fields_]
        )
        short_request.struct_size = ctypes.sizeof(ConstraintRequestV2)
        self.assertEqual(
            self.library.ywta_mesh_smoothing_apply(
                ctypes.cast(ctypes.pointer(short_request), ctypes.POINTER(Request))
            ),
            STATUS_ABI_MISMATCH,
        )

    def test_blender_binding_calls_release_dll(self) -> None:
        blender_binding.reset_dll_cache()
        result = blender_binding.smooth(
            [0.0, 0.0, 0.0, 2.0, 0.0, 0.0],
            [0, 1],
            mode=blender_binding.MODE_HC,
            iterations=1,
        )
        self.assertAlmostEqual(result[0], 0.6)
        self.assertAlmostEqual(result[3], 1.4)


if __name__ == "__main__":
    unittest.main()
