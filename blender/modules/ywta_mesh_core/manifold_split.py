"""split-to-manifold C ABIへのDCC非依存ctypesバインディング。"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass

from . import hair_tube


class ManifoldSplitOutput(ctypes.Structure):
    """C ABIが所有する頂点分離plan。"""

    _fields_ = [
        ("output_vertex_count", ctypes.c_uint64),
        ("corner_count", ctypes.c_uint64),
        ("face_vertices", ctypes.POINTER(ctypes.c_uint32)),
        ("source_vertex_by_output", ctypes.POINTER(ctypes.c_uint32)),
        ("split_edge_count", ctypes.c_uint64),
        ("split_edges", ctypes.POINTER(ctypes.c_uint32)),
        ("split_vertex_count", ctypes.c_uint64),
        ("split_vertices", ctypes.POINTER(ctypes.c_uint32)),
    ]


class ManifoldSplitError(RuntimeError):
    """coreの頂点分離statusと説明を保持する例外。"""

    def __init__(self, status, message):
        self.status = status
        self.diagnostic = message
        super().__init__(f"split-to-manifold planに失敗しました ({status}): {message}")


@dataclass(frozen=True)
class ManifoldSplitPlan:
    """Python側へコピー済みの頂点分離plan。"""

    faces: list[tuple[int, ...]]
    source_vertex_by_output: list[int]
    split_edges: list[tuple[int, int]]
    split_vertices: list[int]

    @property
    def changed(self):
        """頂点分離が1件以上あるか返す。"""
        return len(self.source_vertex_by_output) > len(set(self.source_vertex_by_output))


def _configure(dll):
    dll.ywta_mesh_manifold_split_plan.argtypes = [
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint64),
        ctypes.c_uint64,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.c_uint64,
        ctypes.POINTER(ManifoldSplitOutput),
    ]
    dll.ywta_mesh_manifold_split_plan.restype = ctypes.c_int
    dll.ywta_mesh_manifold_split_free.argtypes = [ctypes.POINTER(ManifoldSplitOutput)]
    dll.ywta_mesh_manifold_split_free.restype = None


def plan(vertex_count, faces):
    """入力を変更せずedge fanとvertex fanの分離planを作る。"""
    if not isinstance(vertex_count, int) or vertex_count < 0:
        raise ValueError("vertex_countは0以上の整数が必要です")
    polygons = [tuple(int(vertex) for vertex in face) for face in faces]
    offsets = [0]
    flat_faces = []
    for face in polygons:
        flat_faces.extend(face)
        offsets.append(len(flat_faces))
    offset_array = (ctypes.c_uint64 * len(offsets))(*offsets)
    face_array = (ctypes.c_uint32 * len(flat_faces))(*flat_faces)
    output = ManifoldSplitOutput()
    dll = hair_tube._load_dll()
    _configure(dll)
    status = int(
        dll.ywta_mesh_manifold_split_plan(
            vertex_count,
            offset_array,
            len(polygons),
            face_array,
            len(flat_faces),
            ctypes.pointer(output),
        )
    )
    if status != 0:
        message = dll.ywta_mesh_core_last_error()
        diagnostic = message.decode("utf-8", errors="replace") if message else "診断なし"
        raise ManifoldSplitError(status, diagnostic)
    try:
        flat_output = [int(output.face_vertices[index]) for index in range(output.corner_count)]
        output_faces = [tuple(flat_output[offsets[face] : offsets[face + 1]]) for face in range(len(polygons))]
        return ManifoldSplitPlan(
            output_faces,
            [int(output.source_vertex_by_output[index]) for index in range(output.output_vertex_count)],
            [
                (int(output.split_edges[index * 2]), int(output.split_edges[index * 2 + 1]))
                for index in range(output.split_edge_count)
            ],
            [int(output.split_vertices[index]) for index in range(output.split_vertex_count)],
        )
    finally:
        dll.ywta_mesh_manifold_split_free(ctypes.pointer(output))
