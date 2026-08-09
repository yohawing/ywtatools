"""RustメッシュスムージングDLLへのctypesバインディング。

``bpy`` に依存しないため、Blender外のPythonでもFFI境界をテストできる。
入力と出力は呼び出し中だけ有効で、DLLへ所有権を渡さない。
"""

from __future__ import annotations

import ctypes
import math
import os
from pathlib import Path


ABI_VERSION = 1

MODE_UNIFORM_LAPLACIAN = 0
MODE_TAUBIN = 1
MODE_HC = 2

CONSTRAINT_FREE = 0
CONSTRAINT_FIXED = 1
CONSTRAINT_SURFACE_PLANE = 2
CONSTRAINT_RAIL_LINE = 3
CONSTRAINT_NORMAL_ONLY = 4

STATUS_MESSAGES = {
    1: "引数が不正です",
    2: "ABIの構造体サイズまたはバージョンが一致しません",
    3: "必要な入力ポインタがNULLです",
    4: "入力要素数がオーバーフローしました",
    5: "出力バッファが不足しています",
    6: "エッジの頂点インデックスが範囲外です",
    7: "入力または計算結果に非有限値があります",
    8: "入力と出力のバッファが重複しています",
    9: "未対応のスムージングモードです",
    10: "Rust内部でpanicが発生しました",
    11: "頂点制約が不正です",
    12: "体積補正用の閉メッシュトポロジーが不正です",
    13: "指定された制約では体積を補正できません",
}

_ENV_VAR = "YWTA_MESH_SMOOTHING_DLL"
_dll = None


class MeshSmoothingOptions(ctypes.Structure):
    """C ABIの56-byteオプション構造体。"""

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


class MeshSmoothingRequest(ctypes.Structure):
    """C ABIの104-byte要求構造体。"""

    _fields_ = [
        ("abi_version", ctypes.c_uint32),
        ("struct_size", ctypes.c_uint32),
        ("positions", ctypes.POINTER(ctypes.c_double)),
        ("position_count", ctypes.c_uint64),
        ("edges", ctypes.POINTER(ctypes.c_uint32)),
        ("edge_count", ctypes.c_uint64),
        ("output", ctypes.POINTER(ctypes.c_double)),
        ("output_len", ctypes.c_uint64),
        ("options", ctypes.POINTER(MeshSmoothingOptions)),
        ("vertex_weights", ctypes.POINTER(ctypes.c_double)),
        ("constraint_modes", ctypes.POINTER(ctypes.c_uint32)),
        ("constraint_directions", ctypes.POINTER(ctypes.c_double)),
        ("triangles", ctypes.POINTER(ctypes.c_uint32)),
        ("triangle_count", ctypes.c_uint64),
    ]


def _validate_abi_layout() -> None:
    """Rust/Cヘッダとctypesの自然アライメントが一致することを確認する。"""
    if ctypes.sizeof(MeshSmoothingOptions) != 56:
        raise RuntimeError("MeshSmoothingOptionsのABIサイズが56 bytesではありません")
    if ctypes.sizeof(MeshSmoothingRequest) != 104:
        raise RuntimeError("MeshSmoothingRequestのABIサイズが104 bytesではありません")


_validate_abi_layout()


class MeshSmoothingError(RuntimeError):
    """Rust DLLが返したステータスコードを保持する例外。"""

    def __init__(self, status: int):
        self.status = status
        message = STATUS_MESSAGES.get(status, "不明なエラーです")
        super().__init__(f"メッシュスムージングに失敗しました ({status}): {message}")


def default_dll_path() -> Path:
    """リポジトリ内の既定DLLパスを返す。"""
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "bin" / "windows" / "ywta_mesh_smoothing.dll"


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
            f"メッシュスムージングDLLが見つかりません: {dll_path}\n"
            f"環境変数 {_ENV_VAR} でパスを指定するか、"
            "<repo>/bin/windows/ywta_mesh_smoothing.dll に配置してください。"
        )
    dll = ctypes.CDLL(str(dll_path))
    dll.ywta_mesh_smoothing_apply.argtypes = [ctypes.POINTER(MeshSmoothingRequest)]
    dll.ywta_mesh_smoothing_apply.restype = ctypes.c_int32
    _dll = dll
    return dll


def reset_dll_cache() -> None:
    """キャッシュ済みDLLを破棄する。主にテストで使用する。"""
    global _dll
    _dll = None


def _flatten(values) -> list:
    """flatまたはnestedなシーケンスを1次元リストへ変換する。"""
    if values is None:
        return []
    if hasattr(values, "ravel"):
        return values.ravel().tolist()
    flattened = []
    for value in values:
        if isinstance(value, (list, tuple)):
            flattened.extend(value)
        elif hasattr(value, "tolist"):
            converted = value.tolist()
            flattened.extend(converted if isinstance(converted, list) else [converted])
        else:
            flattened.append(value)
    return flattened


def _finite_floats(values, name: str, multiple: int) -> list[float]:
    """有限なfloat配列へ変換し、要素数を検証する。"""
    result = [float(value) for value in _flatten(values)]
    if len(result) % multiple != 0:
        raise ValueError(f"{name}の要素数は{multiple}の倍数である必要があります")
    if any(not math.isfinite(value) for value in result):
        raise ValueError(f"{name}には有限値だけを指定してください")
    return result


def _indices(values, name: str, multiple: int, vertex_count: int) -> list[int]:
    """u32頂点インデックス配列へ変換して範囲を検証する。"""
    result = [int(value) for value in _flatten(values)]
    if len(result) % multiple != 0:
        raise ValueError(f"{name}の要素数は{multiple}の倍数である必要があります")
    if any(index < 0 or index >= vertex_count for index in result):
        raise ValueError(f"{name}に範囲外の頂点インデックスがあります")
    return result


def _optional_array(ctype, values):
    """空配列をNULL、非空配列を寿命管理されたctypes配列にする。"""
    return None if not values else (ctype * len(values))(*values)


def smooth(
    positions,
    edges,
    *,
    mode: int = MODE_HC,
    iterations: int = 5,
    strength: float = 0.3,
    taubin_mu: float = -0.34,
    hc_alpha: float = 0.0,
    hc_beta: float = 0.5,
    volume_correction: float = 0.0,
    triangles=None,
    vertex_weights=None,
    constraint_modes=None,
    constraint_directions=None,
) -> list[float]:
    """Rustソルバーを実行し、flatなxyz配列を返す。

    すべての入力配列はこの関数が所有するctypes配列へコピーするため、DLL呼び出し中に
    移動・解放されない。出力は入力と別の配列を確保し、非重複契約を守る。
    """
    flat_positions = _finite_floats(positions, "positions", 3)
    vertex_count = len(flat_positions) // 3
    flat_edges = _indices(edges, "edges", 2, vertex_count)
    flat_triangles = _indices(triangles, "triangles", 3, vertex_count)
    if mode not in {MODE_UNIFORM_LAPLACIAN, MODE_TAUBIN, MODE_HC}:
        raise ValueError("modeが未対応です")
    if int(iterations) < 1:
        raise ValueError("iterationsは1以上である必要があります")

    weights = None
    if vertex_weights is not None:
        weights = _finite_floats(vertex_weights, "vertex_weights", 1)
        if len(weights) != vertex_count or any(not 0.0 <= value <= 1.0 for value in weights):
            raise ValueError("vertex_weightsは頂点数分の[0,1]で指定してください")

    modes = None
    if constraint_modes is not None:
        modes = [int(value) for value in _flatten(constraint_modes)]
        if len(modes) != vertex_count or any(not 0 <= value <= CONSTRAINT_NORMAL_ONLY for value in modes):
            raise ValueError("constraint_modesが不正です")

    directions = None
    if constraint_directions is not None:
        directions = _finite_floats(constraint_directions, "constraint_directions", 3)
        if len(directions) != len(flat_positions):
            raise ValueError("constraint_directionsは頂点数分のxyzが必要です")
    if modes is not None and any(
        value in {CONSTRAINT_SURFACE_PLANE, CONSTRAINT_RAIL_LINE, CONSTRAINT_NORMAL_ONLY}
        for value in modes
    ):
        if directions is None:
            raise ValueError("方向制約にはconstraint_directionsが必要です")
        for vertex, constraint_mode in enumerate(modes):
            if constraint_mode in {
                CONSTRAINT_SURFACE_PLANE,
                CONSTRAINT_RAIL_LINE,
                CONSTRAINT_NORMAL_ONLY,
            }:
                direction = directions[vertex * 3 : vertex * 3 + 3]
                if sum(value * value for value in direction) <= 0.0:
                    raise ValueError("方向制約のベクトルをゼロにはできません")

    positions_array = (ctypes.c_double * len(flat_positions))(*flat_positions)
    edges_array = _optional_array(ctypes.c_uint32, flat_edges)
    triangles_array = _optional_array(ctypes.c_uint32, flat_triangles)
    weights_array = _optional_array(ctypes.c_double, weights)
    modes_array = _optional_array(ctypes.c_uint32, modes)
    directions_array = _optional_array(ctypes.c_double, directions)
    output_array = (ctypes.c_double * len(flat_positions))()
    options = MeshSmoothingOptions(
        ABI_VERSION,
        ctypes.sizeof(MeshSmoothingOptions),
        int(mode),
        int(iterations),
        float(strength),
        float(taubin_mu),
        float(hc_alpha),
        float(hc_beta),
        float(volume_correction),
    )
    request = MeshSmoothingRequest(
        ABI_VERSION,
        ctypes.sizeof(MeshSmoothingRequest),
        positions_array,
        vertex_count,
        edges_array,
        len(flat_edges) // 2,
        output_array,
        len(flat_positions),
        ctypes.pointer(options),
        weights_array,
        modes_array,
        directions_array,
        triangles_array,
        len(flat_triangles) // 3,
    )

    status = int(_load_dll().ywta_mesh_smoothing_apply(ctypes.pointer(request)))
    if status != 0:
        raise MeshSmoothingError(status)
    return list(output_array)
