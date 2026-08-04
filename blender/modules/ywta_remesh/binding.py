"""AutoRemesher DLL への ctypes バインディング。

``bin/windows/ywta_autoremesher.dll``（C ABI）を ctypes で呼び出す薄いラッパー。
bpy に依存しないため、Blender の外（素の Python）からも import・テストできる。

DLLの検索順序:
    1. 環境変数 ``YWTA_AUTOREMESHER_DLL`` で指定されたパス
    2. ``<repo>/bin/windows/ywta_autoremesher.dll``
       （このファイルの3階層上がリポジトリルート: blender/modules/ywta_remesh/ -> リポジトリルート）
"""

import ctypes
import os
from pathlib import Path

# model_type の値（C ABI の enum に対応）
MODEL_TYPE_ORGANIC = 0
MODEL_TYPE_HARDSURFACE = 1

# void (*progress_cb)(void* tag, float progress, const char* message)
ProgressCallbackType = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_float, ctypes.c_char_p)

_ENV_VAR = "YWTA_AUTOREMESHER_DLL"

# _load_dll() でキャッシュされたDLLハンドル（テストでは差し替え可能）
_dll = None


class YwtaRemeshParams(ctypes.Structure):
    """C ABI の ``YwtaRemeshParams`` 構造体に対応する ctypes 構造体。"""

    _fields_ = [
        ("target_triangle_count", ctypes.c_uint64),
        ("scaling", ctypes.c_double),
        ("adaptivity", ctypes.c_double),
        ("model_type", ctypes.c_int),
        ("sharp_edge_degrees", ctypes.c_double),
        ("smooth_normal_degrees", ctypes.c_double),
    ]


def default_dll_path():
    """環境変数を無視した場合のデフォルトDLLパスを返す。

    このファイル（blender/modules/ywta_remesh/binding.py）から3階層上が
    リポジトリルートになる。
    """
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "bin" / "windows" / "ywta_autoremesher.dll"


def resolve_dll_path():
    """DLLの探索順序に従って実際に使用するパスを返す。"""
    env_path = os.environ.get(_ENV_VAR)
    if env_path:
        return Path(env_path)
    return default_dll_path()


def _load_dll():
    """DLLをロードし、関数シグネチャを設定して返す（結果はキャッシュされる）。

    Raises:
        FileNotFoundError: DLLが見つからない場合。
    """
    global _dll
    if _dll is not None:
        return _dll

    dll_path = resolve_dll_path()
    if not dll_path.exists():
        raise FileNotFoundError(
            f"AutoRemesher DLLが見つかりません: {dll_path}\n"
            f"環境変数 {_ENV_VAR} でパスを指定するか、"
            "<repo>/bin/windows/ywta_autoremesher.dll にDLLを配置してください。"
        )

    dll = ctypes.CDLL(str(dll_path))
    dll.ywta_remesh.argtypes = [
        ctypes.POINTER(ctypes.c_double),  # vertices
        ctypes.c_uint64,  # vertex_count
        ctypes.POINTER(ctypes.c_uint32),  # tri_indices
        ctypes.c_uint64,  # tri_count
        ctypes.POINTER(YwtaRemeshParams),  # params
        ProgressCallbackType,  # progress_cb
        ctypes.c_void_p,  # tag
        ctypes.POINTER(ctypes.POINTER(ctypes.c_double)),  # out_vertices
        ctypes.POINTER(ctypes.c_uint64),  # out_vertex_count
        ctypes.POINTER(ctypes.POINTER(ctypes.c_uint32)),  # out_face_indices
        ctypes.POINTER(ctypes.POINTER(ctypes.c_uint32)),  # out_face_counts
        ctypes.POINTER(ctypes.c_uint64),  # out_face_count
    ]
    dll.ywta_remesh.restype = ctypes.c_int

    dll.ywta_remesh_free.argtypes = [
        ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_uint32),
    ]
    dll.ywta_remesh_free.restype = None

    _dll = dll
    return dll


def reset_dll_cache():
    """キャッシュされたDLLハンドルを破棄する（主にテスト用）。"""
    global _dll
    _dll = None


def _flatten_numbers(values):
    """flat・nested（numpy配列含む）のどちらでも1次元のリストに変換する。"""
    if hasattr(values, "ravel"):
        # numpy配列
        return values.ravel().tolist()

    flat = []
    for v in values:
        if isinstance(v, (list, tuple)):
            flat.extend(v)
        elif hasattr(v, "tolist"):
            flat.extend(v.tolist())
        else:
            flat.append(v)
    return flat


def _make_progress_callback(progress_cb):
    """Python callableをC ABIのコールバック関数ポインタに変換する。

    Returns:
        (ctypes関数ポインタ or None, GCされないよう保持しておくオブジェクト)
    """
    if progress_cb is None:
        # argtypes に CFUNCTYPE を指定した関数へは None を直接渡せないため、
        # NULL 関数ポインタにキャストして渡す。
        return ctypes.cast(None, ProgressCallbackType), None

    def _trampoline(_tag, progress, message):
        text = message.decode("utf-8", errors="replace") if message else ""
        progress_cb(progress, text)

    c_callback = ProgressCallbackType(_trampoline)
    return c_callback, c_callback


def remesh(
    vertices,
    triangles,
    *,
    target_count=8000,
    scaling=1.0,
    adaptivity=1.0,
    model_type=MODEL_TYPE_ORGANIC,
    sharp_edge_degrees=90.0,
    smooth_normal_degrees=0.0,
    progress_cb=None,
):
    """AutoRemesherを実行してクアッドメッシュを生成する。

    Args:
        vertices: xyzを1次元に並べたシーケンス（flatなlist/tuple、またはnumpy配列）。
        triangles: 三角形の頂点インデックス。1次元に並べたシーケンス、
            または (i0, i1, i2) のタプルのリストのいずれでも良い。
        target_count: 目標三角形数。
        scaling: エッジ長スケーリング。
        adaptivity: 勾配適応度（0.0〜1.0）。
        model_type: MODEL_TYPE_ORGANIC(0) または MODEL_TYPE_HARDSURFACE(1)。
        sharp_edge_degrees: シャープエッジと判定する角度（度、ライブラリ既定値90.0）。
        smooth_normal_degrees: 法線を平滑化する角度（度、ライブラリ既定値0.0）。
        progress_cb: ``callable(progress: float, message: str) -> None``。
            Noneの場合は進捗通知を行わない。

    Returns:
        tuple[list[float], list[tuple[int, ...]]]: (vertices, faces)
            verticesはxyzを1次元に並べたlist、facesは可変長頂点インデックスの
            タプルのlist（三角形・四角形などが混在しうる）。

    Raises:
        FileNotFoundError: DLLが見つからない場合。
        RuntimeError: ywta_remesh がエラーコードを返した場合。
    """
    dll = _load_dll()

    flat_vertices = [float(v) for v in _flatten_numbers(vertices)]
    flat_tris = [int(i) for i in _flatten_numbers(triangles)]

    vertex_count = len(flat_vertices) // 3
    tri_count = len(flat_tris) // 3

    verts_arr = (ctypes.c_double * len(flat_vertices))(*flat_vertices)
    tris_arr = (ctypes.c_uint32 * len(flat_tris))(*flat_tris)

    params = YwtaRemeshParams(
        target_triangle_count=int(target_count),
        scaling=float(scaling),
        adaptivity=float(adaptivity),
        model_type=int(model_type),
        sharp_edge_degrees=float(sharp_edge_degrees),
        smooth_normal_degrees=float(smooth_normal_degrees),
    )

    c_callback, _keep_alive = _make_progress_callback(progress_cb)

    out_vertices = ctypes.POINTER(ctypes.c_double)()
    out_vertex_count = ctypes.c_uint64()
    out_face_indices = ctypes.POINTER(ctypes.c_uint32)()
    out_face_counts = ctypes.POINTER(ctypes.c_uint32)()
    out_face_count = ctypes.c_uint64()

    result = dll.ywta_remesh(
        verts_arr,
        vertex_count,
        tris_arr,
        tri_count,
        ctypes.pointer(params),
        c_callback,
        None,
        ctypes.pointer(out_vertices),
        ctypes.pointer(out_vertex_count),
        ctypes.pointer(out_face_indices),
        ctypes.pointer(out_face_counts),
        ctypes.pointer(out_face_count),
    )

    if result != 0:
        raise RuntimeError(f"ywta_remesh がエラーコード {result} を返しました")

    try:
        out_vertex_count_val = out_vertex_count.value
        out_face_count_val = out_face_count.value

        result_vertices = list(out_vertices[: out_vertex_count_val * 3])

        face_counts = list(out_face_counts[:out_face_count_val])
        total_indices = sum(face_counts)
        face_indices_flat = list(out_face_indices[:total_indices])

        faces = []
        offset = 0
        for count in face_counts:
            faces.append(tuple(face_indices_flat[offset : offset + count]))
            offset += count
    finally:
        dll.ywta_remesh_free(out_vertices, out_face_indices, out_face_counts)

    return result_vertices, faces
