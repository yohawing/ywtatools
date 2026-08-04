"""ywta_autoremesher.dll の ctypes スモークテスト（純Python、numpy不要）。

立方体（8頂点12三角形）を入力に ywta_remesh() を呼び出し、正常終了と
出力面数 > 0 を確認する。立方体のような小さすぎるメッシュはリメッシュに
失敗する場合が正当にあるため、失敗した場合は手続き的に生成した
アイコスフィア（数百三角形）にフォールバックして再試行する。

実行方法:
    uvx nox -s autoremesher_build  # DLLビルド（bin/windows/ywta_autoremesher.dll）
    python cpp/autoremesher_core/smoke_test.py
"""

from __future__ import annotations

import ctypes
import math
import os
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


class YwtaRemeshParams(ctypes.Structure):
    _fields_ = [
        ("target_triangle_count", ctypes.c_uint64),
        ("scaling", ctypes.c_double),
        ("adaptivity", ctypes.c_double),
        ("model_type", ctypes.c_int),
        ("sharp_edge_degrees", ctypes.c_double),
        ("smooth_normal_degrees", ctypes.c_double),
    ]


YwtaRemeshProgressCallback = ctypes.CFUNCTYPE(
    None, ctypes.c_void_p, ctypes.c_float, ctypes.c_char_p
)

YWTA_MODEL_TYPE_ORGANIC = 0


def find_dll() -> Path:
    """DLL探索順: 環境変数 YWTA_AUTOREMESHER_DLL -> <repo>/bin/windows/ywta_autoremesher.dll"""
    env_path = os.environ.get("YWTA_AUTOREMESHER_DLL")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p
        raise FileNotFoundError(f"YWTA_AUTOREMESHER_DLL で指定されたDLLが見つかりません: {p}")

    default_path = REPO_ROOT / "bin" / "windows" / "ywta_autoremesher.dll"
    if default_path.exists():
        return default_path

    raise FileNotFoundError(
        f"ywta_autoremesher.dll が見つかりません: {default_path}\n"
        "`uvx nox -s autoremesher_build` を実行してビルドしてください。"
    )


def load_library(dll_path: Path):
    lib = ctypes.CDLL(str(dll_path))

    lib.ywta_remesh.argtypes = [
        ctypes.POINTER(ctypes.c_double),
        ctypes.c_uint64,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.c_uint64,
        ctypes.POINTER(YwtaRemeshParams),
        YwtaRemeshProgressCallback,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.POINTER(ctypes.c_double)),
        ctypes.POINTER(ctypes.c_uint64),
        ctypes.POINTER(ctypes.POINTER(ctypes.c_uint32)),
        ctypes.POINTER(ctypes.POINTER(ctypes.c_uint32)),
        ctypes.POINTER(ctypes.c_uint64),
    ]
    lib.ywta_remesh.restype = ctypes.c_int

    lib.ywta_remesh_free.argtypes = [
        ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_uint32),
    ]
    lib.ywta_remesh_free.restype = None

    return lib


def make_cube() -> tuple[list[float], list[int]]:
    """8頂点・12三角形の立方体を返す ([x,y,z,...], [i0,i1,i2,...])。"""
    vertices = [
        (-1.0, -1.0, -1.0),
        (1.0, -1.0, -1.0),
        (1.0, 1.0, -1.0),
        (-1.0, 1.0, -1.0),
        (-1.0, -1.0, 1.0),
        (1.0, -1.0, 1.0),
        (1.0, 1.0, 1.0),
        (-1.0, 1.0, 1.0),
    ]
    faces = [
        (0, 1, 2), (0, 2, 3),  # -Z
        (4, 6, 5), (4, 7, 6),  # +Z
        (0, 4, 5), (0, 5, 1),  # -Y
        (3, 2, 6), (3, 6, 7),  # +Y
        (0, 3, 7), (0, 7, 4),  # -X
        (1, 5, 6), (1, 6, 2),  # +X
    ]
    flat_vertices = [c for v in vertices for c in v]
    flat_indices = [i for f in faces for i in f]
    return flat_vertices, flat_indices


def make_icosphere(subdivisions: int = 2) -> tuple[list[float], list[int]]:
    """手続き的に生成するアイコスフィア（外部ファイル依存なし）。

    subdivisions=2 で 20 * 4^2 = 320 三角形になる。
    """
    t = (1.0 + math.sqrt(5.0)) / 2.0
    raw_vertices = [
        (-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0),
        (0, -1, t), (0, 1, t), (0, -1, -t), (0, 1, -t),
        (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1),
    ]

    def normalize(v: tuple[float, float, float]) -> tuple[float, float, float]:
        length = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
        return (v[0] / length, v[1] / length, v[2] / length)

    vertices = [normalize(v) for v in raw_vertices]
    faces = [
        (0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11),
        (1, 5, 9), (5, 11, 4), (11, 10, 2), (10, 7, 6), (7, 1, 8),
        (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9),
        (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1),
    ]

    midpoint_cache: dict[tuple[int, int], int] = {}

    def midpoint(i0: int, i1: int) -> int:
        key = (min(i0, i1), max(i0, i1))
        if key in midpoint_cache:
            return midpoint_cache[key]
        a = vertices[i0]
        b = vertices[i1]
        mid = normalize(((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0, (a[2] + b[2]) / 2.0))
        vertices.append(mid)
        index = len(vertices) - 1
        midpoint_cache[key] = index
        return index

    for _ in range(subdivisions):
        new_faces = []
        for (i0, i1, i2) in faces:
            a = midpoint(i0, i1)
            b = midpoint(i1, i2)
            c = midpoint(i2, i0)
            new_faces.append((i0, a, c))
            new_faces.append((i1, b, a))
            new_faces.append((i2, c, b))
            new_faces.append((a, b, c))
        faces = new_faces

    flat_vertices = [c for v in vertices for c in v]
    flat_indices = [i for f in faces for i in f]
    return flat_vertices, flat_indices


def run_remesh(lib, flat_vertices: list[float], flat_indices: list[int], target_triangle_count: int = 400):
    vertex_count = len(flat_vertices) // 3
    tri_count = len(flat_indices) // 3

    c_vertices = (ctypes.c_double * len(flat_vertices))(*flat_vertices)
    c_indices = (ctypes.c_uint32 * len(flat_indices))(*flat_indices)

    params = YwtaRemeshParams(
        target_triangle_count=target_triangle_count,
        scaling=1.0,  # AutoRemesher本家GUIの既定値（0.0だと結果が退化する）
        adaptivity=1.0,
        model_type=YWTA_MODEL_TYPE_ORGANIC,
        sharp_edge_degrees=90.0,  # ライブラリ既定値
        smooth_normal_degrees=0.0,  # ライブラリ既定値
    )

    messages: list[str] = []

    @YwtaRemeshProgressCallback
    def on_progress(_tag, progress, status):
        text = status.decode("utf-8", errors="replace") if status else ""
        messages.append(f"{progress * 100:5.1f}% {text}")

    out_vertices = ctypes.POINTER(ctypes.c_double)()
    out_vertex_count = ctypes.c_uint64(0)
    out_face_indices = ctypes.POINTER(ctypes.c_uint32)()
    out_face_counts = ctypes.POINTER(ctypes.c_uint32)()
    out_face_count = ctypes.c_uint64(0)

    result = lib.ywta_remesh(
        c_vertices,
        vertex_count,
        c_indices,
        tri_count,
        ctypes.byref(params),
        on_progress,
        None,
        ctypes.byref(out_vertices),
        ctypes.byref(out_vertex_count),
        ctypes.byref(out_face_indices),
        ctypes.byref(out_face_counts),
        ctypes.byref(out_face_count),
    )

    try:
        if result != 0 or out_face_count.value == 0:
            return result, 0, 0, Counter(), messages

        vertex_result_count = out_vertex_count.value
        face_result_count = out_face_count.value
        face_size_histogram: Counter[int] = Counter(
            out_face_counts[i] for i in range(face_result_count)
        )
        return result, vertex_result_count, face_result_count, face_size_histogram, messages
    finally:
        lib.ywta_remesh_free(out_vertices, out_face_indices, out_face_counts)


def main() -> int:
    dll_path = find_dll()
    print(f"DLL: {dll_path}")
    lib = load_library(dll_path)

    print("== cube (8 verts / 12 tris) ==")
    flat_vertices, flat_indices = make_cube()
    result, vcount, fcount, histogram, messages = run_remesh(lib, flat_vertices, flat_indices, target_triangle_count=400)
    print(f"result={result} out_vertex_count={vcount} out_face_count={fcount} face_size_histogram={dict(histogram)}")
    if messages:
        print(f"progress messages: {len(messages)} (last: {messages[-1]!r})")

    if result == 0 and fcount > 0:
        print("cube remesh OK")
        return 0

    print("cube remesh は結果が空/失敗だったため、アイコスフィア(320tri)にフォールバックします。")
    flat_vertices, flat_indices = make_icosphere(subdivisions=2)
    print(f"== icosphere ({len(flat_vertices) // 3} verts / {len(flat_indices) // 3} tris) ==")
    result, vcount, fcount, histogram, messages = run_remesh(lib, flat_vertices, flat_indices, target_triangle_count=400)
    print(f"result={result} out_vertex_count={vcount} out_face_count={fcount} face_size_histogram={dict(histogram)}")
    if messages:
        print(f"progress messages: {len(messages)} (last: {messages[-1]!r})")

    assert result == 0, f"ywta_remesh failed with code {result}"
    assert fcount > 0, "out_face_count must be > 0"
    print("icosphere remesh OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
