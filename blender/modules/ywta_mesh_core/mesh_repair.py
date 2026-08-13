"""安全mesh修復plan C ABIへのDCC非依存ctypesバインディング。"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass

from . import hair_tube
from . import mesh_diagnostics


class MeshRepairOutput(ctypes.Structure):
    """C ABIが所有する安全修復plan。"""

    _fields_ = [
        ("output_face_count", ctypes.c_uint64),
        ("output_corner_count", ctypes.c_uint64),
        ("face_offsets", ctypes.POINTER(ctypes.c_uint64)),
        ("face_vertices", ctypes.POINTER(ctypes.c_uint32)),
        ("old_face_to_new", ctypes.POINTER(ctypes.c_uint64)),
        ("source_face_by_output", ctypes.POINTER(ctypes.c_uint64)),
        ("source_corner_by_output", ctypes.POINTER(ctypes.c_uint64)),
        ("removed_zero_area_count", ctypes.c_uint64),
        ("removed_zero_area_faces", ctypes.POINTER(ctypes.c_uint64)),
        ("removed_duplicate_count", ctypes.c_uint64),
        ("removed_duplicate_faces", ctypes.POINTER(ctypes.c_uint64)),
        ("flipped_face_count", ctypes.c_uint64),
        ("flipped_source_faces", ctypes.POINTER(ctypes.c_uint64)),
    ]


class MeshRepairError(RuntimeError):
    """coreの修復statusと説明を保持する例外。"""

    def __init__(self, status, message):
        self.status = status
        self.diagnostic = message
        super().__init__(f"Mesh安全修復planに失敗しました ({status}): {message}")


@dataclass(frozen=True)
class MeshRepairPlan:
    """Python側へコピー済みの安全修復plan。"""

    faces: list[tuple[int, ...]]
    old_face_to_new: list[int | None]
    source_face_by_output: list[int]
    source_corner_by_output: list[int]
    removed_zero_area_faces: list[int]
    removed_duplicate_faces: list[int]
    flipped_source_faces: list[int]

    @property
    def changed(self):
        """削除または反転が1件以上あるか返す。"""
        return bool(self.removed_zero_area_faces or self.removed_duplicate_faces or self.flipped_source_faces)


def _configure(dll):
    dll.ywta_mesh_repair_plan.argtypes = [
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_uint64),
        ctypes.c_uint64,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.c_uint64,
        ctypes.c_double,
        ctypes.POINTER(MeshRepairOutput),
    ]
    dll.ywta_mesh_repair_plan.restype = ctypes.c_int
    dll.ywta_mesh_repair_free.argtypes = [ctypes.POINTER(MeshRepairOutput)]
    dll.ywta_mesh_repair_free.restype = None


def plan(positions, faces, *, area_epsilon=1.0e-12):
    """入力を変更せず安全修復planを作る。"""
    points, polygons, epsilon = mesh_diagnostics._validate_inputs(positions, faces, area_epsilon)
    flat_positions = [value for point in points for value in point]
    offsets = [0]
    flat_faces = []
    for face in polygons:
        flat_faces.extend(face)
        offsets.append(len(flat_faces))
    position_array = (ctypes.c_double * len(flat_positions))(*flat_positions)
    offset_array = (ctypes.c_uint64 * len(offsets))(*offsets)
    face_array = (ctypes.c_uint32 * len(flat_faces))(*flat_faces)
    output = MeshRepairOutput()
    dll = hair_tube._load_dll()
    _configure(dll)
    status = int(
        dll.ywta_mesh_repair_plan(
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
        raise MeshRepairError(status, diagnostic)
    try:
        offsets_copy = [int(output.face_offsets[index]) for index in range(output.output_face_count + 1)]
        output_faces = [
            tuple(int(output.face_vertices[index]) for index in range(offsets_copy[face], offsets_copy[face + 1]))
            for face in range(output.output_face_count)
        ]
        removed = 0xFFFFFFFFFFFFFFFF
        return MeshRepairPlan(
            output_faces,
            [
                None if int(output.old_face_to_new[index]) == removed else int(output.old_face_to_new[index])
                for index in range(len(polygons))
            ],
            [int(output.source_face_by_output[index]) for index in range(output.output_face_count)],
            [int(output.source_corner_by_output[index]) for index in range(output.output_corner_count)],
            [int(output.removed_zero_area_faces[index]) for index in range(output.removed_zero_area_count)],
            [int(output.removed_duplicate_faces[index]) for index in range(output.removed_duplicate_count)],
            [int(output.flipped_source_faces[index]) for index in range(output.flipped_face_count)],
        )
    finally:
        dll.ywta_mesh_repair_free(ctypes.pointer(output))
