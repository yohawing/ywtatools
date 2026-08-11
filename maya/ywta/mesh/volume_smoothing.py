"""Maya向けRustメッシュスムージングコマンド。

メッシュの取得、選択範囲と境界の固定、Undo/RedoはMaya側で行い、数値計算は
``blender/modules/ywta_mesh_smoothing/binding.py`` の共有ctypesバインディングに
委譲する。通常コマンドと、API 2.0のMPxContextブラシを提供する。
"""

from __future__ import annotations

import sys
import heapq
import math
from pathlib import Path

import maya.api.OpenMaya as om2
import maya.api.OpenMayaUI as omui
import maya.cmds as cmds


_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_SHARED_MODULES = _REPOSITORY_ROOT / "blender" / "modules"
if str(_SHARED_MODULES) not in sys.path:
    sys.path.insert(0, str(_SHARED_MODULES))

from ywta_mesh_smoothing import binding as _binding  # noqa: E402


COMMAND_NAME = "ywtaVolumeSmooth"
BRUSH_CONTEXT_NAME = "ywtaVolumeSmoothBrushContext"
BRUSH_CONTEXT_INSTANCE_NAME = "ywtaVolumeSmoothBrushContext1"
BRUSH_COMMIT_COMMAND_NAME = "ywtaVolumeSmoothBrushCommit"

# Context解放と通常MPxCommandの間で1ストロークだけ受け渡す。
_PENDING_BRUSH_TRANSACTION = None
DEFAULT_MODE = _binding.MODE_HC
DEFAULT_ITERATIONS = 5
DEFAULT_STRENGTH = 0.3
DEFAULT_VOLUME_CORRECTION = 1.0
DEFAULT_PRESERVE_RAILS = True
_RAIL_CORNER_DOT = -0.8660254037844386


def _attribute_value(value):
    """Maya APIのproperty/method差を吸収して値を返す。"""
    return value() if callable(value) else value


def _rich_vertex_weights(shape_path, vertex_count):
    """Maya Soft Selectionを頂点ごとの連続ウェイトとして取得する。"""
    try:
        selection = om2.MGlobal.getRichSelection().getSelection()
    except RuntimeError:
        return {}

    weights = {}
    for item_index in range(selection.length()):
        try:
            dag_path, component = selection.getComponent(item_index)
        except (AttributeError, RuntimeError, TypeError):
            continue
        if dag_path.node().hasFn(om2.MFn.kTransform):
            dag_path.extendToShape()
        if dag_path.fullPathName() != shape_path or component.apiType() != om2.MFn.kMeshVertComponent:
            continue
        component_fn = om2.MFnSingleIndexedComponent(component)
        for local_index, vertex in enumerate(component_fn.getElements()):
            vertex = int(vertex)
            if 0 <= vertex < vertex_count:
                influence = component_fn.weight(local_index).influence if component_fn.hasWeights else 1.0
                weights[vertex] = max(weights.get(vertex, 0.0), float(influence))
    return weights


def _shape_selection():
    """現在の選択からメッシュ形状、連続ウェイト、選択エッジを取得する。"""
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
    selected_edges = set()
    if component_is_null:
        selected = set(range(vertex_count))
        selection_weights = [1.0] * vertex_count
    else:
        api_type = _attribute_value(getattr(component, "apiType", None))
        component_fn = om2.MFnSingleIndexedComponent(component)
        elements = {int(index) for index in component_fn.getElements()}
        if api_type == om2.MFn.kMeshVertComponent:
            rich_weights = _rich_vertex_weights(dag_path.fullPathName(), vertex_count)
            selected = {index for index in elements if 0 <= index < vertex_count}
            selected.update(index for index, weight in rich_weights.items() if weight > 0.0)
            selection_weights = [rich_weights.get(index, 1.0 if index in elements else 0.0) for index in range(vertex_count)]
        elif api_type == om2.MFn.kMeshEdgeComponent:
            selected_edges = {index for index in elements if 0 <= index < mesh_fn.numEdges}
            selected = set(range(vertex_count))
            selection_weights = [1.0] * vertex_count
        elif api_type == om2.MFn.kMeshPolygonComponent:
            selected = {
                int(vertex)
                for face in elements
                if 0 <= face < mesh_fn.numPolygons
                for vertex in mesh_fn.getPolygonVertices(face)
            }
            selection_weights = [1.0 if index in selected else 0.0 for index in range(vertex_count)]
        else:
            raise RuntimeError("メッシュ、頂点、エッジ、または面を選択してください")

    positions = []
    for point in points:
        positions.extend((float(point.x), float(point.y), float(point.z)))

    edges, triangles, closed = _mesh_topology(mesh_fn)
    rail_edges = _mesh_rail_edges(mesh_fn, selected_edges)
    return (
        dag_path.fullPathName(),
        positions,
        edges,
        triangles,
        closed,
        selected,
        selection_weights,
        rail_edges,
    )


def _mesh_topology(mesh_fn):
    """Mayaの面リストから重複のない辺と実三角形を作る。"""
    face_counts, face_indices = mesh_fn.getVertices()
    edges = set()
    edge_use_counts = {}
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

    # 非平面quad/ngonでもMayaが評価する面と一致する三角形をRustへ渡す。
    _triangle_counts, triangle_indices = mesh_fn.getTriangles()
    triangles = [int(index) for index in triangle_indices]

    # API 2.0のMFnMeshにはisClosedプロパティがないため、各辺の面使用数で判定する。
    is_closed = bool(edge_use_counts) and all(count == 2 for count in edge_use_counts.values())
    edge_values = [value for edge in sorted(edges) for value in edge]
    return edge_values, triangles, is_closed


def _mesh_rail_edges(mesh_fn, selected_edge_ids):
    """hard edge、crease、明示選択エッジを頂点ペアで返す。"""
    try:
        crease_ids, crease_values = mesh_fn.getCreaseEdges()
        creased = {int(edge) for edge, value in zip(crease_ids, crease_values) if float(value) > 0.0}
    except RuntimeError:
        creased = set()

    face_counts, face_indices = mesh_fn.getVertices()
    edge_use_counts = {}
    offset = 0
    for raw_count in face_counts:
        count = int(raw_count)
        vertices = [int(index) for index in face_indices[offset : offset + count]]
        offset += count
        for first, second in zip(vertices, vertices[1:] + vertices[:1]):
            edge = (min(first, second), max(first, second))
            edge_use_counts[edge] = edge_use_counts.get(edge, 0) + 1

    rail_edges = []
    for edge_id in range(mesh_fn.numEdges):
        first, second = mesh_fn.getEdgeVertices(edge_id)
        edge = (min(int(first), int(second)), max(int(first), int(second)))
        auto_hard = edge_use_counts.get(edge, 0) == 2 and not mesh_fn.isEdgeSmooth(edge_id)
        if edge_id not in selected_edge_ids and edge_id not in creased and not auto_hard:
            continue
        rail_edges.extend((int(first), int(second)))
    return rail_edges


def _constraints(vertex_count, edges, selected, selection_weights=None):
    """未選択頂点と選択境界を固定し、連続ウェイトを保持する。"""
    neighbours = [set() for _ in range(vertex_count)]
    for first, second in zip(edges[::2], edges[1::2]):
        neighbours[first].add(second)
        neighbours[second].add(first)

    free = {vertex for vertex in selected if all(neighbour in selected for neighbour in neighbours[vertex])}
    modes = [_binding.CONSTRAINT_FREE if vertex in free else _binding.CONSTRAINT_FIXED for vertex in range(vertex_count)]
    source_weights = selection_weights or [1.0] * vertex_count
    weights = [float(source_weights[vertex]) if vertex in free else 0.0 for vertex in range(vertex_count)]
    return weights, modes, free


def _apply_rail_constraints(positions, rail_edges, weights, modes):
    """rail chain内部を接線移動へ制限し、端点・分岐・鋭角を固定する。"""
    vertex_count = len(positions) // 3
    neighbours = [set() for _ in range(vertex_count)]
    for first, second in zip(rail_edges[::2], rail_edges[1::2]):
        neighbours[first].add(second)
        neighbours[second].add(first)

    directions = [0.0] * len(positions)
    for vertex, rail_neighbours in enumerate(neighbours):
        if not rail_neighbours or modes[vertex] == _binding.CONSTRAINT_FIXED:
            continue
        if len(rail_neighbours) != 2:
            modes[vertex] = _binding.CONSTRAINT_FIXED
            weights[vertex] = 0.0
            continue
        first, second = sorted(rail_neighbours)
        origin = positions[vertex * 3 : vertex * 3 + 3]
        vectors = []
        for neighbour in (first, second):
            vector = [positions[neighbour * 3 + axis] - origin[axis] for axis in range(3)]
            length = math.sqrt(sum(value * value for value in vector))
            if length <= 1.0e-12:
                vectors = []
                break
            vectors.append([value / length for value in vector])
        if len(vectors) != 2 or sum(a * b for a, b in zip(*vectors)) > _RAIL_CORNER_DOT:
            modes[vertex] = _binding.CONSTRAINT_FIXED
            weights[vertex] = 0.0
            continue
        tangent = [vectors[0][axis] - vectors[1][axis] for axis in range(3)]
        length = math.sqrt(sum(value * value for value in tangent))
        if length <= 1.0e-12:
            modes[vertex] = _binding.CONSTRAINT_FIXED
            weights[vertex] = 0.0
            continue
        modes[vertex] = _binding.CONSTRAINT_RAIL_LINE
        for axis in range(3):
            directions[vertex * 3 + axis] = tangent[axis] / length
    return directions


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
    preserve_rails=DEFAULT_PRESERVE_RAILS,
):
    """選択メッシュをRustで処理し、Undo用の前後座標を返す。"""
    shape_path, before, edges, triangles, closed, selected, selection_weights, rail_edges = _shape_selection()
    vertex_count = len(before) // 3
    if not selected:
        return shape_path, before, list(before)

    weights, modes, _free = _constraints(vertex_count, edges, selected, selection_weights)
    directions = _apply_rail_constraints(before, rail_edges, weights, modes) if preserve_rails else None
    # Rust側は固定点を含む閉メッシュの体積補正に対応している。
    correction = float(volume_correction) if closed else 0.0
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
            constraint_directions=directions,
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
        "preserveRails": kwargs.pop("preserveRails", DEFAULT_PRESERVE_RAILS),
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
        syntax.addFlag("-pr", "-preserveRails", om2.MSyntax.kBoolean)
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
        preserve_rails = database.flagArgumentBool("-pr", 0) if database.isFlagSet("-pr") else DEFAULT_PRESERVE_RAILS
        self._shape_path, self._before, self._after = _compute_result(
            mode=mode,
            iterations=iterations,
            strength=strength,
            volume_correction=volume_correction,
            preserve_rails=preserve_rails,
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


def _geodesic_brush_weights(
    positions,
    edges,
    faces,
    face_index,
    hit_point,
    radius,
    strength,
    selected,
    boundary_vertices,
):
    """ヒット面から辺距離を辿り、滑らかなブラシ重みを生成する。

    距離と半径はobject-spaceで扱う。これにより、変換済みメッシュでもrayと
    ジオデシック計算の空間が一致する。
    """
    vertex_count = len(positions) // 3
    weights = [0.0] * vertex_count
    if radius <= 0.0 or face_index < 0 or face_index >= len(faces):
        return weights
    hit_face = faces[face_index]
    if not hit_face:
        return weights

    points = [positions[index * 3 : index * 3 + 3] for index in range(vertex_count)]
    adjacency = [[] for _ in range(vertex_count)]
    for first, second in zip(edges[::2], edges[1::2]):
        delta = [points[first][axis] - points[second][axis] for axis in range(3)]
        length = math.sqrt(sum(value * value for value in delta))
        adjacency[first].append((second, length))
        adjacency[second].append((first, length))

    distances = [math.inf] * vertex_count
    queue = []
    for vertex in hit_face:
        delta = [points[vertex][axis] - hit_point[axis] for axis in range(3)]
        distance = math.sqrt(sum(value * value for value in delta))
        if distance <= radius:
            distances[vertex] = distance
            heapq.heappush(queue, (distance, vertex))

    while queue:
        distance, vertex = heapq.heappop(queue)
        if distance != distances[vertex] or distance > radius:
            continue
        for neighbour, edge_length in adjacency[vertex]:
            candidate = distance + edge_length
            if candidate <= radius and candidate < distances[neighbour]:
                distances[neighbour] = candidate
                heapq.heappush(queue, (candidate, neighbour))

    for vertex, distance in enumerate(distances):
        if vertex not in selected or vertex in boundary_vertices or distance > radius:
            continue
        normalized = max(0.0, min(1.0, 1.0 - distance / radius))
        falloff = normalized * normalized * (3.0 - 2.0 * normalized)
        weights[vertex] = max(0.0, min(1.0, strength * falloff))
    return weights


def _mesh_faces(mesh_fn):
    """MFnMeshの面頂点配列をPythonの面リストへ変換する。"""
    face_counts, face_indices = mesh_fn.getVertices()
    faces = []
    offset = 0
    for raw_count in face_counts:
        count = int(raw_count)
        faces.append([int(index) for index in face_indices[offset : offset + count]])
        offset += count
    return faces


class _BrushSessionCache:
    """ストローク中にトポロジーとRustセッションを再利用するキャッシュ。"""

    def __init__(self, shape_path, positions, edges, triangles, faces, closed, selected):
        self.shape_path = shape_path
        self.positions = list(positions)
        self.edges = list(edges)
        self.triangles = list(triangles)
        self.faces = list(faces)
        self.closed = bool(closed)
        self.selected = set(selected)
        self.vertex_count = len(self.positions) // 3
        self.face_count = len(self.faces)
        self.session = _binding.MeshSmoothingSession(
            self.vertex_count,
            self.edges,
            self.triangles if self.closed else None,
        )
        self.boundary_vertices = self._find_boundaries()

    def is_valid(self):
        """頂点数・面数がキャッシュ構築時から変わっていないか確認する。"""
        try:
            selection = om2.MSelectionList()
            selection.add(self.shape_path)
            dag_path = selection.getDagPath(0)
            mesh_fn = om2.MFnMesh(dag_path)
            return mesh_fn.numVertices == self.vertex_count and mesh_fn.numPolygons == self.face_count
        except (RuntimeError, TypeError):
            return False

    @classmethod
    def from_active_selection(cls):
        """現在の選択からキャッシュを構築する。"""
        shape_path, positions, edges, triangles, closed, selected, _weights, _rails = _shape_selection()
        selection = om2.MSelectionList()
        selection.add(shape_path)
        dag_path = selection.getDagPath(0)
        faces = _mesh_faces(om2.MFnMesh(dag_path))
        return cls(shape_path, positions, edges, triangles, faces, closed, selected)

    def _find_boundaries(self):
        """開境界と選択範囲境界の頂点を返す。"""
        vertex_count = len(self.positions) // 3
        neighbours = [set() for _ in range(vertex_count)]
        edge_faces = {}
        for face in self.faces:
            for first, second in zip(face, face[1:] + face[:1]):
                edge = (min(first, second), max(first, second))
                edge_faces[edge] = edge_faces.get(edge, 0) + 1
                neighbours[first].add(second)
                neighbours[second].add(first)
        boundary = {vertex for edge, count in edge_faces.items() if count != 2 for vertex in edge}
        boundary.update(
            vertex for vertex in self.selected if any(neighbour not in self.selected for neighbour in neighbours[vertex])
        )
        return boundary

    def apply_dab(self, hit_point, face_index, radius, strength):
        """1 dabを適用し、座標が変化したかを返す。"""
        weights = _geodesic_brush_weights(
            self.positions,
            self.edges,
            self.faces,
            face_index,
            hit_point,
            radius,
            strength,
            self.selected,
            self.boundary_vertices,
        )
        if not any(weight > 0.0 for weight in weights):
            return False
        modes = [
            _binding.CONSTRAINT_FIXED
            if vertex in self.boundary_vertices or weights[vertex] <= 0.0
            else _binding.CONSTRAINT_FREE
            for vertex in range(len(weights))
        ]
        result = self.session.apply(
            self.positions,
            mode=_binding.MODE_HC,
            iterations=1,
            strength=0.3,
            volume_correction=1.0 if self.closed else 0.0,
            vertex_weights=weights,
            constraint_modes=modes,
        )
        changed = result != self.positions
        self.positions = list(result)
        return changed


class _BrushStrokeTransaction:
    """テストフックとcommit MPxCommandが共有する1ストローク状態。"""

    def __init__(self, shape_path, before, after):
        self.shape_path = shape_path
        self.before = list(before)
        self.after = list(after)

    def undoIt(self):
        """1ストローク分の変更を元へ戻す。"""
        _apply_points(self.shape_path, self.before)

    def redoIt(self):
        """1ストローク分の変更を再適用する。"""
        _apply_points(self.shape_path, self.after)


class VolumeSmoothingBrushCommitCommand(om2.MPxCommand):
    """保留中の1ストロークをMayaのUndo managerへ登録するコマンド。"""

    def __init__(self):
        super().__init__()
        self._transaction = None

    @staticmethod
    def creator():
        """Mayaプラグイン用creator。"""
        return VolumeSmoothingBrushCommitCommand()

    def doIt(self, _args):
        """保留トランザクションを取り込み、座標は既に適用済みとして確定する。"""
        global _PENDING_BRUSH_TRANSACTION
        self._transaction = _PENDING_BRUSH_TRANSACTION
        _PENDING_BRUSH_TRANSACTION = None
        if self._transaction is None:
            raise RuntimeError("確定待ちのブラシストロークがありません")

    def isUndoable(self):
        """1ストロークをMayaのUndoキューへ登録する。"""
        return True

    def undoIt(self):
        """ストローク全体をUndoする。"""
        if self._transaction:
            self._transaction.undoIt()

    def redoIt(self):
        """ストローク全体をRedoする。"""
        if self._transaction:
            self._transaction.redoIt()


class VolumeSmoothingBrushContext(omui.MPxContext):
    """object-spaceのジオデシックfalloffブラシ。"""

    def __init__(self):
        super().__init__()
        self.setTitleString("YWTA Volume Smooth Brush")
        self.setHelpString("LMB drag: smooth | radius is object-space")
        self.radius = 0.25
        self.strength = 0.5
        self._cache = None
        self._stroke_before = None
        self._stroke_active = False
        self._stroke_changed = False

    def toolOnSetup(self, _event):
        """ツール有効化時にトポロジーとRustセッションを一度だけ構築する。"""
        try:
            self._cache = _BrushSessionCache.from_active_selection()
        except (RuntimeError, ValueError, FileNotFoundError) as error:
            om2.MGlobal.displayError(str(error))
            self._cache = None

    def toolOffCleanup(self):
        """ツール終了時に未確定ストロークを破棄する。"""
        if self._stroke_active and self._cache:
            self._restore_stroke()
        self._cache = None
        self._stroke_active = False
        self._stroke_changed = False

    def _event_hit(self, event):
        """イベント位置からobject-spaceのメッシュ交点と面番号を得る。"""
        if self._cache is None:
            return None
        position = event.position
        view = omui.M3dView.active3dView()
        selection = om2.MSelectionList()
        selection.add(self._cache.shape_path)
        dag_path = selection.getDagPath(0)
        origin = om2.MPoint()
        direction = om2.MVector()
        view.viewToObjectSpace(
            int(position[0]),
            int(position[1]),
            dag_path.inclusiveMatrixInverse(),
            origin,
            direction,
        )
        mesh_fn = om2.MFnMesh(dag_path)
        hit = mesh_fn.closestIntersection(
            origin,
            direction,
            om2.MSpace.kObject,
            1.0e6,
            False,
        )
        if hit is None:
            return None
        return hit[0], int(hit[2])

    def _begin_stroke(self):
        if self._cache is None:
            return False
        self._stroke_before = list(self._cache.positions)
        self._stroke_active = True
        self._stroke_changed = False
        return True

    def _apply_hit(self, hit):
        if not hit or self._cache is None:
            return
        if not self._cache.is_valid():
            self.abortAction()
            self._cache = None
            om2.MGlobal.displayError("メッシュトポロジーが変化したためブラシを終了しました")
            return
        try:
            changed = self._cache.apply_dab(hit[0], hit[1], self.radius, self.strength)
        except Exception as error:
            self._restore_stroke()
            self._stroke_active = False
            self._stroke_before = None
            self._stroke_changed = False
            om2.MGlobal.displayError(f"ブラシストロークを取り消しました: {error}")
            return
        if changed:
            _apply_points(self._cache.shape_path, self._cache.positions)
            self._stroke_changed = True

    def _finish_stroke(self, journal=True):
        if not self._stroke_active or self._cache is None:
            return None
        transaction = None
        if self._stroke_changed:
            transaction = _BrushStrokeTransaction(
                self._cache.shape_path,
                self._stroke_before,
                self._cache.positions,
            )
            if journal:
                global _PENDING_BRUSH_TRANSACTION
                _PENDING_BRUSH_TRANSACTION = transaction
                try:
                    cmds.ywtaVolumeSmoothBrushCommit()
                except Exception:
                    _PENDING_BRUSH_TRANSACTION = None
                    transaction.undoIt()
                    raise
        self._stroke_active = False
        self._stroke_before = None
        self._stroke_changed = False
        return transaction

    def doPress(self, event, _draw_manager, _frame_context):
        """左ボタン押下でストロークを開始する。"""
        if event.mouseButton() != omui.MEvent.kLeftMouse or not self._begin_stroke():
            return
        self._apply_hit(self._event_hit(event))

    def doDrag(self, event, _draw_manager, _frame_context):
        """ドラッグ中は同じsessionへdabを追加する。"""
        if self._stroke_active:
            self._apply_hit(self._event_hit(event))

    def doRelease(self, event, _draw_manager, _frame_context):
        """左ボタン解放で1ストロークを1Undoへ確定する。"""
        if event.mouseButton() == omui.MEvent.kLeftMouse:
            self._apply_hit(self._event_hit(event))
            try:
                self._finish_stroke()
            except Exception as error:
                om2.MGlobal.displayError(f"ブラシストロークの確定に失敗しました: {error}")

    def abortAction(self):
        """Esc等で未確定ストロークを取り消す。"""
        if self._stroke_active and self._cache:
            self._restore_stroke()
        self._stroke_active = False
        self._stroke_before = None
        self._stroke_changed = False

    def apply_stroke_for_test(self, hit_points, face_index=0):
        """GUIイベントを合成できない環境向けの1ストロークテストフック。"""
        if not self._begin_stroke():
            return None
        for hit_point in hit_points:
            self._apply_hit((hit_point, face_index))
        return self._finish_stroke(journal=True)

    def _restore_stroke(self):
        """現在ストロークの開始座標へ戻し、過去の確定結果は保持する。"""
        if self._cache is not None and self._stroke_before is not None:
            self._cache.positions = list(self._stroke_before)
            _apply_points(self._cache.shape_path, self._stroke_before)


class VolumeSmoothingBrushContextCommand(omui.MPxContextCommand):
    """ブラシコンテキストの登録コマンド。"""

    @staticmethod
    def creator():
        """Mayaプラグイン用creator。"""
        return VolumeSmoothingBrushContextCommand()

    def makeObj(self):
        """API 2.0コンテキストを生成する。"""
        return VolumeSmoothingBrushContext()


def activate_volume_smooth_brush(*_args):
    """プラグインをロードし、ブラシコンテキストをアクティブ化する。"""
    try:
        loaded = bool(cmds.pluginInfo("ywtaVolumeSmoothing.py", query=True, loaded=True))
    except (AttributeError, RuntimeError):
        loaded = False
    if not loaded:
        plugin_path = _REPOSITORY_ROOT / "maya" / "plug-ins" / "ywtaVolumeSmoothing.py"
        cmds.loadPlugin(str(plugin_path), quiet=True)
    if not cmds.contextInfo(BRUSH_CONTEXT_INSTANCE_NAME, exists=True):
        cmds.ywtaVolumeSmoothBrushContext(BRUSH_CONTEXT_INSTANCE_NAME)
    cmds.setToolTo(BRUSH_CONTEXT_INSTANCE_NAME)
    return BRUSH_CONTEXT_INSTANCE_NAME
