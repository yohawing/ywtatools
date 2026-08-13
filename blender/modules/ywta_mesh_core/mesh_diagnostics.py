"""共有mesh診断C ABIへのDCC非依存ctypesバインディング。"""

from __future__ import annotations

import ctypes
import math
from dataclasses import dataclass

from . import hair_tube


class MeshDiagnosticOutput(ctypes.Structure):
    """C ABIが所有するmesh診断結果。"""

    _fields_ = [
        ("zero_area_face_count", ctypes.c_uint64),
        ("zero_area_faces", ctypes.POINTER(ctypes.c_uint64)),
        ("duplicate_face_count", ctypes.c_uint64),
        ("duplicate_faces", ctypes.POINTER(ctypes.c_uint64)),
        ("non_manifold_edge_count", ctypes.c_uint64),
        ("non_manifold_edges", ctypes.POINTER(ctypes.c_uint32)),
        ("winding_conflict_edge_count", ctypes.c_uint64),
        ("winding_conflict_edges", ctypes.POINTER(ctypes.c_uint32)),
        ("bow_tie_vertex_count", ctypes.c_uint64),
        ("bow_tie_vertices", ctypes.POINTER(ctypes.c_uint32)),
        ("boundary_loop_count", ctypes.c_uint64),
        ("boundary_loop_offsets", ctypes.POINTER(ctypes.c_uint64)),
        ("boundary_loop_vertices", ctypes.POINTER(ctypes.c_uint32)),
    ]


class MeshDiagnosticError(RuntimeError):
    """coreの診断statusと説明を保持する例外。"""

    def __init__(self, status, message):
        self.status = status
        self.diagnostic = message
        super().__init__(f"Mesh診断に失敗しました ({status}): {message}")


@dataclass(frozen=True)
class MeshDiagnosticReport:
    """Python側へコピー済みのmesh診断結果。"""

    zero_area_faces: list[int]
    duplicate_faces: list[int]
    non_manifold_edges: list[tuple[int, int]]
    winding_conflict_edges: list[tuple[int, int]]
    bow_tie_vertices: list[int]
    boundary_loops: list[list[int]]

    @property
    def issue_count(self) -> int:
        """boundaryを除く診断件数を返す。"""
        return sum(
            len(values)
            for values in (
                self.zero_area_faces,
                self.duplicate_faces,
                self.non_manifold_edges,
                self.winding_conflict_edges,
                self.bow_tie_vertices,
            )
        )


def _configure(dll):
    """診断C ABIのシグネチャを設定する。"""
    dll.ywta_mesh_diagnose.argtypes = [
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_uint64),
        ctypes.c_uint64,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.c_uint64,
        ctypes.c_double,
        ctypes.POINTER(MeshDiagnosticOutput),
    ]
    dll.ywta_mesh_diagnose.restype = ctypes.c_int
    dll.ywta_mesh_diagnostic_free.argtypes = [ctypes.POINTER(MeshDiagnosticOutput)]
    dll.ywta_mesh_diagnostic_free.restype = None


def _validate_inputs(positions, faces, area_epsilon):
    """Python入力を検証し、正規化済み配列を返す。"""
    points = [tuple(float(component) for component in point) for point in positions]
    polygons = [tuple(int(vertex) for vertex in face) for face in faces]
    epsilon = float(area_epsilon)
    if len(points) > 0xFFFFFFFF or any(len(point) != 3 for point in points):
        raise ValueError("positionsはu32範囲内のxyz配列で指定してください")
    if any(not math.isfinite(value) for point in points for value in point):
        raise ValueError("positionsには有限値だけを指定してください")
    if any(len(face) < 3 for face in polygons):
        raise ValueError("facesは3頂点以上で指定してください")
    if any(vertex < 0 or vertex >= len(points) for face in polygons for vertex in face):
        raise ValueError("facesに範囲外の頂点があります")
    if not math.isfinite(epsilon) or epsilon < 0.0:
        raise ValueError("area_epsilonは有限な0以上で指定してください")
    return points, polygons, epsilon


def diagnose(positions, faces, *, area_epsilon=1.0e-12):
    """位置とface配列を変更せず診断する。"""
    points, polygons, epsilon = _validate_inputs(positions, faces, area_epsilon)

    flat_positions = [value for point in points for value in point]
    offsets = [0]
    flat_faces = []
    for face in polygons:
        flat_faces.extend(face)
        offsets.append(len(flat_faces))
    position_array = (ctypes.c_double * len(flat_positions))(*flat_positions)
    offset_array = (ctypes.c_uint64 * len(offsets))(*offsets)
    face_array = (ctypes.c_uint32 * len(flat_faces))(*flat_faces)
    output = MeshDiagnosticOutput()
    dll = hair_tube._load_dll()
    _configure(dll)
    status = int(
        dll.ywta_mesh_diagnose(
            len(points),
            position_array,
            offset_array,
            len(polygons),
            face_array,
            len(flat_faces),
            epsilon,
            ctypes.pointer(output),
        )
    )
    if status != 0:
        message = dll.ywta_mesh_core_last_error()
        diagnostic = message.decode("utf-8", errors="replace") if message else "診断なし"
        raise MeshDiagnosticError(status, diagnostic)
    try:

        def edge_list(pointer, count):
            return [(int(pointer[index * 2]), int(pointer[index * 2 + 1])) for index in range(count)]

        offsets_copy = [int(output.boundary_loop_offsets[index]) for index in range(output.boundary_loop_count + 1)]
        loops = [
            [int(output.boundary_loop_vertices[index]) for index in range(offsets_copy[loop], offsets_copy[loop + 1])]
            for loop in range(output.boundary_loop_count)
        ]
        return MeshDiagnosticReport(
            [int(output.zero_area_faces[index]) for index in range(output.zero_area_face_count)],
            [int(output.duplicate_faces[index]) for index in range(output.duplicate_face_count)],
            edge_list(output.non_manifold_edges, output.non_manifold_edge_count),
            edge_list(output.winding_conflict_edges, output.winding_conflict_edge_count),
            [int(output.bow_tie_vertices[index]) for index in range(output.bow_tie_vertex_count)],
            loops,
        )
    finally:
        dll.ywta_mesh_diagnostic_free(ctypes.pointer(output))
