"""Maya向けRustメッシュスムージングコマンド。

メッシュの取得、選択範囲と境界の固定、Undo/RedoはMaya側で行い、数値計算は
``blender/modules/ywta_mesh_smoothing/binding.py`` の共有ctypesバインディングに
委譲する。ブラシやMPxContextはこのモジュールの責務に含めない。
"""

from __future__ import annotations

import sys
from pathlib import Path

import maya.api.OpenMaya as om2
import maya.cmds as cmds


_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_SHARED_MODULES = _REPOSITORY_ROOT / "blender" / "modules"
if str(_SHARED_MODULES) not in sys.path:
    sys.path.insert(0, str(_SHARED_MODULES))

from ywta_mesh_smoothing import binding as _binding  # noqa: E402


COMMAND_NAME = "ywtaVolumeSmooth"
DEFAULT_MODE = _binding.MODE_HC
DEFAULT_ITERATIONS = 5
DEFAULT_STRENGTH = 0.3
DEFAULT_VOLUME_CORRECTION = 1.0


def _attribute_value(value):
    """Maya APIのproperty/method差を吸収して値を返す。"""
    return value() if callable(value) else value


def _shape_selection():
    """現在の選択からメッシュ形状、頂点集合、object-space座標を取得する。"""
    selection = om2.MGlobal.getActiveSelectionList()
    if selection.length() != 1:
        raise RuntimeError("メッシュを1つだけ選択してください")

    try:
        dag_path, component = selection.getComponent(0)
    except (AttributeError, RuntimeError, TypeError):
        dag_path = selection.getDagPath(0)
        component = om2.MObject.kNullObj

    if dag_path.node().hasFn(om2.MFn.kTransform):
        dag_path.extendToShape()
    if not dag_path.node().hasFn(om2.MFn.kMesh):
        raise RuntimeError("選択項目がメッシュではありません")

    mesh_fn = om2.MFnMesh(dag_path)
    points = mesh_fn.getPoints(om2.MSpace.kObject)
    vertex_count = len(points)
    if vertex_count == 0:
        raise RuntimeError("メッシュに頂点がありません")

    component_is_null = _attribute_value(getattr(component, "isNull", True))
    if component_is_null:
        selected = set(range(vertex_count))
    else:
        api_type = _attribute_value(getattr(component, "apiType", None))
        if api_type != om2.MFn.kMeshVertComponent:
            raise RuntimeError("頂点コンポーネントを選択してください")
        selected = {int(index) for index in om2.MFnSingleIndexedComponent(component).getElements()}
        selected = {index for index in selected if 0 <= index < vertex_count}

    positions = []
    for point in points:
        positions.extend((float(point.x), float(point.y), float(point.z)))

    edges, triangles, closed = _mesh_topology(mesh_fn)
    return dag_path.fullPathName(), positions, edges, triangles, closed, selected


def _mesh_topology(mesh_fn):
    """Mayaの面リストから重複のない辺と閉メッシュ用三角形を作る。"""
    face_counts, face_indices = mesh_fn.getVertices()
    edges = set()
    edge_use_counts = {}
    triangles = []
    offset = 0
    for raw_count in face_counts:
        count = int(raw_count)
        vertices = [int(index) for index in face_indices[offset : offset + count]]
        offset += count
        if count < 3:
            continue
        for first, second in zip(vertices, vertices[1:] + vertices[:1]):
            edge = (min(first, second), max(first, second))
            edges.add(edge)
            edge_use_counts[edge] = edge_use_counts.get(edge, 0) + 1
        # Mayaの面頂点順序を保ったファン分割。Rust側が閉包性と向きを検証する。
        for index in range(1, count - 1):
            triangles.extend((vertices[0], vertices[index], vertices[index + 1]))

    # API 2.0のMFnMeshにはisClosedプロパティがないため、各辺の面使用数で判定する。
    is_closed = bool(edge_use_counts) and all(count == 2 for count in edge_use_counts.values())
    edge_values = [value for edge in sorted(edges) for value in edge]
    return edge_values, triangles, is_closed


def _constraints(vertex_count, edges, selected):
    """未選択頂点と選択境界を固定するRust制約配列を作る。"""
    neighbours = [set() for _ in range(vertex_count)]
    for first, second in zip(edges[::2], edges[1::2]):
        neighbours[first].add(second)
        neighbours[second].add(first)

    free = {vertex for vertex in selected if all(neighbour in selected for neighbour in neighbours[vertex])}
    modes = [_binding.CONSTRAINT_FREE if vertex in free else _binding.CONSTRAINT_FIXED for vertex in range(vertex_count)]
    weights = [1.0 if vertex in free else 0.0 for vertex in range(vertex_count)]
    return weights, modes, free


def _apply_points(shape_path, flat_positions):
    """指定形状へobject-space座標を書き戻す。"""
    selection = om2.MSelectionList()
    selection.add(shape_path)
    dag_path = selection.getDagPath(0)
    mesh_fn = om2.MFnMesh(dag_path)
    points = [
        om2.MPoint(flat_positions[index], flat_positions[index + 1], flat_positions[index + 2])
        for index in range(0, len(flat_positions), 3)
    ]
    mesh_fn.setPoints(points, om2.MSpace.kObject)


def _compute_result(
    *,
    mode=DEFAULT_MODE,
    iterations=DEFAULT_ITERATIONS,
    strength=DEFAULT_STRENGTH,
    volume_correction=DEFAULT_VOLUME_CORRECTION,
):
    """選択メッシュをRustで処理し、Undo用の前後座標を返す。"""
    shape_path, before, edges, triangles, closed, selected = _shape_selection()
    vertex_count = len(before) // 3
    if not selected:
        return shape_path, before, list(before)

    weights, modes, free = _constraints(vertex_count, edges, selected)
    # 部分選択では固定境界があるため、全体体積を補正しようとすると不定になる。
    # 全頂点が可動で、かつRustが検証できる閉メッシュの場合だけ補正を有効にする。
    correction = float(volume_correction) if closed and len(free) == vertex_count else 0.0
    try:
        after = _binding.smooth(
            before,
            edges,
            mode=int(mode),
            iterations=int(iterations),
            strength=float(strength),
            volume_correction=correction,
            triangles=triangles if correction > 0.0 else None,
            vertex_weights=weights,
            constraint_modes=modes,
        )
    except Exception as error:
        # DLLエラーをMayaのコマンド失敗へ変換し、書き戻しは行わない。
        raise RuntimeError(f"Rustメッシュスムージングに失敗しました: {error}") from error
    if len(after) != len(before):
        raise RuntimeError("Rustソルバーの出力頂点数が一致しません")
    return shape_path, before, [float(value) for value in after]


def smooth_selected_mesh(**kwargs):
    """通常操作用の簡易入口。コマンドをロードして既定設定で実行する。"""
    command_kwargs = {
        "mode": kwargs.pop("mode", DEFAULT_MODE),
        "iterations": kwargs.pop("iterations", DEFAULT_ITERATIONS),
        "strength": kwargs.pop("strength", DEFAULT_STRENGTH),
        "volumeCorrection": kwargs.pop("volumeCorrection", DEFAULT_VOLUME_CORRECTION),
    }
    if kwargs:
        raise TypeError(f"未対応の引数です: {', '.join(sorted(kwargs))}")
    try:
        loaded = bool(cmds.pluginInfo("ywtaVolumeSmoothing.py", query=True, loaded=True))
    except (AttributeError, RuntimeError):
        loaded = False
    if not loaded:
        plugin_path = _REPOSITORY_ROOT / "maya" / "plug-ins" / "ywtaVolumeSmoothing.py"
        cmds.loadPlugin(str(plugin_path), quiet=True)
    return cmds.ywtaVolumeSmooth(**command_kwargs)


class VolumeSmoothingCommand(om2.MPxCommand):
    """選択メッシュをUndo可能にスムージングするAPI 2.0コマンド。"""

    def __init__(self):
        super().__init__()
        self._shape_path = None
        self._before = None
        self._after = None

    @staticmethod
    def creator():
        """Mayaプラグイン用のコマンド生成関数。"""
        return VolumeSmoothingCommand()

    @staticmethod
    def createSyntax():
        """コマンドフラグを定義する。"""
        syntax = om2.MSyntax()
        syntax.addFlag("-m", "-mode", om2.MSyntax.kLong)
        syntax.addFlag("-i", "-iterations", om2.MSyntax.kLong)
        syntax.addFlag("-s", "-strength", om2.MSyntax.kDouble)
        syntax.addFlag("-v", "-volumeCorrection", om2.MSyntax.kDouble)
        return syntax

    def isUndoable(self):
        """座標配列を保持するためUndo可能とする。"""
        return True

    def doIt(self, args):
        """選択メッシュを処理し、前後座標を保存する。"""
        database = om2.MArgDatabase(self.syntax(), args)
        mode = database.flagArgumentInt("-m", 0) if database.isFlagSet("-m") else DEFAULT_MODE
        iterations = database.flagArgumentInt("-i", 0) if database.isFlagSet("-i") else DEFAULT_ITERATIONS
        strength = database.flagArgumentDouble("-s", 0) if database.isFlagSet("-s") else DEFAULT_STRENGTH
        volume_correction = database.flagArgumentDouble("-v", 0) if database.isFlagSet("-v") else DEFAULT_VOLUME_CORRECTION
        self._shape_path, self._before, self._after = _compute_result(
            mode=mode,
            iterations=iterations,
            strength=strength,
            volume_correction=volume_correction,
        )
        _apply_points(self._shape_path, self._after)

    def redoIt(self):
        """保存済みの結果座標を再適用する。"""
        if self._shape_path is not None and self._after is not None:
            _apply_points(self._shape_path, self._after)

    def undoIt(self):
        """保存済みの元座標へ戻す。"""
        if self._shape_path is not None and self._before is not None:
            _apply_points(self._shape_path, self._before)
