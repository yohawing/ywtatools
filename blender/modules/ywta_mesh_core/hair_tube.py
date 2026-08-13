"""Hair Tube C ABIへのbpy非依存ctypesバインディング。"""

from __future__ import annotations

import ctypes
import math
import os
from dataclasses import dataclass
from pathlib import Path


_ENV_VAR = "YWTA_MESH_CORE_DLL"
_dll = None


class HairTubeOutput(ctypes.Structure):
    """C ABIが所有する再生成結果。"""

    _fields_ = [
        ("vertex_count", ctypes.c_uint64),
        ("quad_count", ctypes.c_uint64),
        ("positions_xyz", ctypes.POINTER(ctypes.c_double)),
        ("quad_indices", ctypes.POINTER(ctypes.c_uint32)),
        ("source_intervals", ctypes.POINTER(ctypes.c_uint64)),
        ("source_alphas", ctypes.POINTER(ctypes.c_double)),
        ("source_station_count", ctypes.c_uint64),
        ("max_fit_deviation", ctypes.c_double),
        ("max_source_distance", ctypes.c_double),
        ("cubic_active", ctypes.c_int),
    ]


@dataclass(frozen=True)
class GeneratedHairTube:
    """Python側へコピー済みの再生成結果。"""

    positions: list[tuple[float, float, float]]
    quads: list[tuple[int, int, int, int]]
    source_mapping: list[tuple[int, float]]
    source_station_count: int
    max_fit_deviation: float
    max_source_distance: float
    cubic_active: bool


class HairTubeError(RuntimeError):
    """coreのstatusと診断を保持する例外。"""

    def __init__(self, status: int, message: str):
        self.status = status
        self.diagnostic = message
        super().__init__(f"Hair Tube生成に失敗しました ({status}): {message}")


def default_dll_path() -> Path:
    """リポジトリ内の既定DLLパスを返す。"""
    return Path(__file__).resolve().parents[3] / "bin" / "windows" / "ywta_mesh_core.dll"


def resolve_dll_path() -> Path:
    """環境変数を優先してDLLパスを解決する。"""
    configured = os.environ.get(_ENV_VAR)
    return Path(configured) if configured else default_dll_path()


def _load_dll():
    """DLLをロードしてC関数シグネチャを設定する。"""
    global _dll
    if _dll is not None:
        return _dll
    dll_path = resolve_dll_path()
    if not dll_path.exists():
        raise FileNotFoundError(
            f"Hair Tube DLLが見つかりません: {dll_path}\n"
            f"環境変数 {_ENV_VAR} で指定するか、uvx nox -s mesh_core_tests を実行してください。"
        )
    dll = ctypes.CDLL(str(dll_path))
    dll.ywta_hair_tube_generate.argtypes = [
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_uint64),
        ctypes.c_uint64,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.c_uint64,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.c_uint64,
        ctypes.c_double,
        ctypes.POINTER(HairTubeOutput),
    ]
    dll.ywta_hair_tube_generate.restype = ctypes.c_int
    dll.ywta_hair_tube_free.argtypes = [ctypes.POINTER(HairTubeOutput)]
    dll.ywta_hair_tube_free.restype = None
    dll.ywta_mesh_core_last_error.argtypes = []
    dll.ywta_mesh_core_last_error.restype = ctypes.c_char_p
    _dll = dll
    return dll


def reset_dll_cache() -> None:
    """キャッシュ済みDLLを破棄する。主にテストで使用する。"""
    global _dll
    _dll = None


def _validate_inputs(positions, faces, root_vertices, target_segments, fit_tolerance):
    """Python入力を有限かつABIへ渡せるflat配列へ変換する。"""
    points = [tuple(float(component) for component in point) for point in positions]
    if len(points) > 0xFFFFFFFF or any(len(point) != 3 for point in points):
        raise ValueError("positionsはu32範囲内のxyz配列で指定してください")
    if any(not math.isfinite(component) for point in points for component in point):
        raise ValueError("positionsには有限値だけを指定してください")
    polygons = [tuple(int(index) for index in face) for face in faces]
    if any(len(face) < 3 for face in polygons):
        raise ValueError("facesは3頂点以上で指定してください")
    if any(index < 0 or index >= len(points) for face in polygons for index in face):
        raise ValueError("facesに範囲外の頂点があります")
    root = tuple(int(index) for index in root_vertices)
    if len(root) != 4 or len(set(root)) != 4 or any(index < 0 or index >= len(points) for index in root):
        raise ValueError("root_verticesは異なる4頂点を巡回順で指定してください")
    segments = int(target_segments)
    tolerance = float(fit_tolerance)
    if segments < 1:
        raise ValueError("target_segmentsは1以上で指定してください")
    if not math.isfinite(tolerance) or tolerance < 0.0:
        raise ValueError("fit_toleranceは有限な0以上で指定してください")
    offsets = [0]
    flat_faces = []
    for face in polygons:
        flat_faces.extend(face)
        offsets.append(len(flat_faces))
    return points, offsets, flat_faces, root, segments, tolerance


def generate(positions, faces, root_vertices, *, target_segments=8, fit_tolerance=0.0):
    """root loopから別object用の固定密度quad tubeデータを生成する。"""
    points, offsets, flat_faces, root, segments, tolerance = _validate_inputs(
        positions, faces, root_vertices, target_segments, fit_tolerance
    )
    flat_positions = [component for point in points for component in point]
    positions_array = (ctypes.c_double * len(flat_positions))(*flat_positions)
    offsets_array = (ctypes.c_uint64 * len(offsets))(*offsets)
    faces_array = (ctypes.c_uint32 * len(flat_faces))(*flat_faces)
    root_array = (ctypes.c_uint32 * 4)(*root)
    output = HairTubeOutput()
    dll = _load_dll()
    status = int(
        dll.ywta_hair_tube_generate(
            len(points),
            positions_array,
            offsets_array,
            len(offsets) - 1,
            faces_array,
            len(flat_faces),
            root_array,
            segments,
            tolerance,
            ctypes.pointer(output),
        )
    )
    if status != 0:
        message = dll.ywta_mesh_core_last_error()
        diagnostic = message.decode("utf-8", errors="replace") if message else "診断なし"
        raise HairTubeError(status, diagnostic)
    try:
        output_positions = [
            tuple(output.positions_xyz[index * 3 + axis] for axis in range(3)) for index in range(output.vertex_count)
        ]
        quads = [
            tuple(int(output.quad_indices[index * 4 + corner]) for corner in range(4)) for index in range(output.quad_count)
        ]
        mapping = [
            (int(output.source_intervals[index]), float(output.source_alphas[index])) for index in range(output.vertex_count)
        ]
        return GeneratedHairTube(
            output_positions,
            quads,
            mapping,
            int(output.source_station_count),
            float(output.max_fit_deviation),
            float(output.max_source_distance),
            bool(output.cubic_active),
        )
    finally:
        dll.ywta_hair_tube_free(ctypes.pointer(output))
