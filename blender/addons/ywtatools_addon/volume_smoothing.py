"""Rustソルバーを使うEdit Modeメッシュスムージングオペレータ。"""

import heapq
import math
import os
import sys

import bmesh
import bpy
from bpy_extras import view3d_utils
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty
from bpy.types import Operator
from mathutils import Vector
from mathutils.bvhtree import BVHTree

try:
    import ywta_mesh_smoothing.binding as binding
except ImportError:
    _modules_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "modules"))
    if _modules_dir not in sys.path:
        sys.path.append(_modules_dir)
    import ywta_mesh_smoothing.binding as binding


_MODE_ITEMS = (
    ("HC", "HC", "元形状を参照し、収縮を抑えてスムージング", 0),
    ("TAUBIN", "Taubin", "λ/μの二段パスで収縮を抑制", 1),
    ("UNIFORM", "Uniform", "均一Laplacianによる比較用スムージング", 2),
)
_MODE_VALUES = {
    "HC": binding.MODE_HC,
    "TAUBIN": binding.MODE_TAUBIN,
    "UNIFORM": binding.MODE_UNIFORM_LAPLACIAN,
}

_BRUSH_MODE_ITEMS = (
    ("SMOOTH", "Smooth", "HCで形状を保ちながらスムージング", 0),
    ("VOLUME", "Volume", "閉メッシュの全体体積を保ちながらブラシ範囲をスムージング", 1),
    ("BUMPS", "Remove Bumps", "頂点法線方向だけに移動して凹凸を除去", 2),
)

_RAIL_CORNER_DOT = -0.8660254037844386
_WEIGHT_EPSILON = 1.0e-8


def _is_closed_mesh(bm) -> bool:
    """全エッジがちょうど2面を共有する閉メッシュか判定する。"""
    return bool(bm.faces) and all(len(edge.link_faces) == 2 for edge in bm.edges)


def _is_selection_boundary(vertex, selected_indices=None) -> bool:
    """未選択領域またはメッシュ境界に接する頂点か判定する。"""
    if selected_indices is None:
        return any(
            len(edge.link_faces) != 2 or not edge.other_vert(vertex).select
            for edge in vertex.link_edges
        )
    return any(
        len(edge.link_faces) != 2
        or edge.other_vert(vertex).index not in selected_indices
        for edge in vertex.link_edges
    )


def _vertex_group_weights(obj, bm, group_name):
    """指定Vertex Groupを頂点ごとの連続ウェイトへ変換する。"""
    if not group_name:
        return None
    try:
        group = obj.vertex_groups.get(group_name)
    except (AttributeError, TypeError):
        return [0.0] * len(bm.verts)
    if group is None:
        return [0.0] * len(bm.verts)

    weights = []
    for vertex in bm.verts:
        try:
            value = float(group.weight(vertex.index))
        except (RuntimeError, ValueError):
            value = 0.0
        value = max(0.0, min(1.0, value))
        weights.append(value)
    return weights


def _selection_weights(bm):
    """現在の頂点／面選択を0または1のマスクへ変換する。"""
    try:
        edge_select_mode = bool(bpy.context.tool_settings.mesh_select_mode[1])
    except (AttributeError, TypeError, IndexError):
        edge_select_mode = False
    if edge_select_mode and any(edge.select for edge in bm.edges):
        # EDGE選択はrail指定として扱い、非表示頂点以外を連続maskの対象にする。
        selected = {vertex.index for vertex in bm.verts if not vertex.hide}
        return [1.0 if vertex.index in selected else 0.0 for vertex in bm.verts], selected
    selected = {vertex.index for vertex in bm.verts if vertex.select}
    if not selected:
        selected = {vertex.index for face in bm.faces if face.select for vertex in face.verts}
    return [1.0 if vertex.index in selected else 0.0 for vertex in bm.verts], selected


def _crease_layer(bm):
    """Blender世代差を吸収してエッジcreaseレイヤーを取得する。"""
    try:
        return bm.edges.layers.float.get("crease_edge")
    except AttributeError:
        return None


def _edge_is_rail_candidate(edge, crease_layer, include_selected_edges):
    """hard edge、seam、crease、EDGE選択をrail候補として判定する。"""
    if include_selected_edges and edge.select:
        return True
    if edge.seam:
        return True
    if crease_layer is not None:
        try:
            if float(edge[crease_layer]) > _WEIGHT_EPSILON:
                return True
        except (KeyError, TypeError, ValueError):
            pass
    # 開境界のhard edgeは既存のpreserve_boundaryで固定し、内部edgeだけを
    # rail候補にする。明示的なEDGE選択・seam・creaseは境界でも上で許可する。
    return len(edge.link_faces) == 2 and not edge.smooth


def _rail_constraints(bm, include_selected_edges=None):
    """rail候補をchain内部の方向制約と固定端点へ分類する。

    戻り値は頂点ごとの制約モードとobject-space方向ベクトル。候補辺の次数が
    2で、かつ直線に近い頂点だけがRAIL_LINEとなり、端点・分岐・cornerはFIXED
    になる。方向はRustソルバーへそのまま渡せる局所接線である。
    """
    if include_selected_edges is None:
        try:
            include_selected_edges = bool(bpy.context.tool_settings.mesh_select_mode[1])
        except (AttributeError, TypeError, IndexError):
            include_selected_edges = False

    crease_layer = _crease_layer(bm)
    adjacency = {vertex.index: [] for vertex in bm.verts}
    for edge in bm.edges:
        if not _edge_is_rail_candidate(edge, crease_layer, include_selected_edges):
            continue
        first, second = edge.verts
        adjacency[first.index].append(second)
        adjacency[second.index].append(first)

    modes = [binding.CONSTRAINT_FREE] * len(bm.verts)
    directions = [Vector((0.0, 0.0, 1.0)) for _ in bm.verts]
    for vertex in bm.verts:
        neighbours = adjacency.get(vertex.index, ())
        if not neighbours:
            continue
        if len(neighbours) != 2:
            modes[vertex.index] = binding.CONSTRAINT_FIXED
            continue
        first, second = neighbours
        first_direction = first.co - vertex.co
        second_direction = second.co - vertex.co
        if first_direction.length_squared <= _WEIGHT_EPSILON or second_direction.length_squared <= _WEIGHT_EPSILON:
            modes[vertex.index] = binding.CONSTRAINT_FIXED
            continue
        first_direction.normalize()
        second_direction.normalize()
        # 直線上では2本の外向きベクトルが反対向きになる。角度が鋭い
        # cornerは固定し、chain内部だけをrail方向へ射影する。
        if first_direction.dot(second_direction) > _RAIL_CORNER_DOT:
            modes[vertex.index] = binding.CONSTRAINT_FIXED
            continue
        tangent = first_direction - second_direction
        if tangent.length_squared <= _WEIGHT_EPSILON:
            modes[vertex.index] = binding.CONSTRAINT_FIXED
            continue
        modes[vertex.index] = binding.CONSTRAINT_RAIL_LINE
        directions[vertex.index] = tangent.normalized()
    return modes, directions


def _geodesic_brush_weights(
    bm,
    face_index,
    hit_local,
    matrix_world,
    radius,
    strength,
    use_selection_mask,
    preserve_boundary,
):
    """ヒット面からエッジ距離を辿り、裏面を巻き込まないfalloffを生成する。"""
    weights = [0.0] * len(bm.verts)
    if radius <= 0.0 or face_index < 0 or face_index >= len(bm.faces):
        return weights
    face = bm.faces[face_index]
    if face.hide:
        return weights

    hit_world = matrix_world @ hit_local
    distances = [math.inf] * len(bm.verts)
    queue = []
    for vertex in face.verts:
        distance = ((matrix_world @ vertex.co) - hit_world).length
        if distance <= radius:
            distances[vertex.index] = distance
            heapq.heappush(queue, (distance, vertex.index))

    while queue:
        distance, vertex_index = heapq.heappop(queue)
        if distance != distances[vertex_index] or distance > radius:
            continue
        vertex = bm.verts[vertex_index]
        for edge in vertex.link_edges:
            neighbour = edge.other_vert(vertex)
            edge_length = ((matrix_world @ vertex.co) - (matrix_world @ neighbour.co)).length
            candidate = distance + edge_length
            if candidate <= radius and candidate < distances[neighbour.index]:
                distances[neighbour.index] = candidate
                heapq.heappush(queue, (candidate, neighbour.index))

    for vertex in bm.verts:
        distance = distances[vertex.index]
        masked = use_selection_mask and not vertex.select
        boundary = preserve_boundary and (
            any(len(edge.link_faces) != 2 for edge in vertex.link_edges)
            or (use_selection_mask and _is_selection_boundary(vertex))
        )
        if vertex.hide or masked or boundary or distance > radius:
            continue
        normalized = 1.0 - distance / radius
        falloff = normalized * normalized * (3.0 - 2.0 * normalized)
        weights[vertex.index] = max(0.0, min(1.0, strength * falloff))
    return weights


def _apply_brush_solver(bm, session, weights, brush_mode, closed_mesh, iterations):
    """ブラシ重みと現在BMesh座標をRustソルバーへ渡す。"""
    normal_only = brush_mode == "BUMPS"
    modes = []
    directions = []
    for vertex, weight in zip(bm.verts, weights):
        modes.append(
            binding.CONSTRAINT_NORMAL_ONLY
            if normal_only and weight > 0.0
            else binding.CONSTRAINT_FREE
        )
        normal = vertex.normal.normalized() if vertex.normal.length_squared > 0.0 else Vector((0, 0, 1))
        directions.extend(normal)
    positions = [component for vertex in bm.verts for component in vertex.co]
    result = session.apply(
        positions,
        mode=binding.MODE_HC,
        iterations=iterations,
        strength=0.3,
        hc_alpha=0.0,
        hc_beta=0.5,
        volume_correction=1.0 if brush_mode == "VOLUME" and closed_mesh else 0.0,
        vertex_weights=weights,
        constraint_modes=modes,
        constraint_directions=directions,
    )
    for vertex in bm.verts:
        start = vertex.index * 3
        vertex.co = result[start : start + 3]
    bm.normal_update()


class YWTA_OT_volume_smooth(Operator):
    """選択頂点をRustソルバーでスムージングする。"""

    bl_idname = "ywta.volume_smooth"
    bl_label = "Volume Preserving Smooth"
    bl_description = "選択頂点を収縮を抑えながらスムージングします"
    bl_options = {"REGISTER", "UNDO"}

    mode: EnumProperty(name="方式", items=_MODE_ITEMS, default="HC")
    iterations: IntProperty(name="反復回数", default=5, min=1, max=100)
    strength: FloatProperty(name="強さ", default=0.3, min=0.0, max=1.0)
    taubin_mu: FloatProperty(name="Taubin μ", default=-0.34, min=-1.0, max=-0.0001)
    hc_alpha: FloatProperty(name="HC α", default=0.0, min=0.0, max=1.0)
    hc_beta: FloatProperty(name="HC β", default=0.5, min=0.0, max=1.0)
    preserve_volume: BoolProperty(
        name="閉メッシュの体積を保持",
        description="閉メッシュでは初期符号付き体積へ補正し、開メッシュではHCのみ使います",
        default=True,
    )
    normal_only: BoolProperty(
        name="法線方向のみ",
        description="接線方向のドリフトを避け、元メッシュの頂点法線方向だけに移動します",
        default=False,
    )
    preserve_boundary: BoolProperty(
        name="選択境界を固定",
        description="未選択領域または開境界に接する選択頂点を固定します",
        default=True,
    )
    preserve_rails: BoolProperty(
        name="Railを保持",
        description="hard edge、seam、crease、EDGE選択を連続したrailとして保持します",
        default=True,
    )
    mask_vertex_group: StringProperty(
        name="Mask Vertex Group",
        description="連続マスクに使うVertex Group。空欄なら現在の頂点選択を使います",
        default="",
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "MESH" and obj.mode == "EDIT"

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "mode")
        layout.prop(self, "iterations")
        layout.prop(self, "strength")
        if self.mode == "TAUBIN":
            layout.prop(self, "taubin_mu")
        if self.mode == "HC":
            layout.prop(self, "hc_alpha")
            layout.prop(self, "hc_beta")
        layout.prop(self, "preserve_volume")
        layout.prop(self, "normal_only")
        layout.prop(self, "preserve_boundary")
        layout.prop(self, "preserve_rails")
        layout.prop_search(self, "mask_vertex_group", context.active_object, "vertex_groups")

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != "MESH" or obj.mode != "EDIT":
            self.report({"ERROR"}, "メッシュのEdit Modeで実行してください")
            return {"CANCELLED"}

        mesh = obj.data
        bm = bmesh.from_edit_mesh(mesh)
        bm.verts.ensure_lookup_table()
        bm.verts.index_update()
        bm.normal_update()
        group_weights = _vertex_group_weights(obj, bm, self.mask_vertex_group)
        if group_weights is None:
            weights, selected_indices = _selection_weights(bm)
        else:
            weights = group_weights
            selected_indices = {
                vertex.index for vertex, weight in zip(bm.verts, weights) if weight > _WEIGHT_EPSILON
            }
        if not selected_indices:
            self.report({"WARNING"}, "スムージングする頂点を選択してください")
            return {"CANCELLED"}

        positions = [component for vertex in bm.verts for component in vertex.co]
        edges = [index for edge in bm.edges for index in (edge.verts[0].index, edge.verts[1].index)]
        rail_modes, rail_directions = _rail_constraints(bm) if self.preserve_rails else (
            [binding.CONSTRAINT_FREE] * len(bm.verts),
            [Vector((0.0, 0.0, 1.0)) for _ in bm.verts],
        )
        constraint_modes = []
        directions = []
        for vertex in bm.verts:
            fixed = vertex.index not in selected_indices
            if self.preserve_boundary and _is_selection_boundary(vertex, selected_indices):
                fixed = True
            if self.preserve_rails and rail_modes[vertex.index] == binding.CONSTRAINT_FIXED:
                fixed = True
            if fixed:
                constraint_modes.append(binding.CONSTRAINT_FIXED)
            elif self.preserve_rails and rail_modes[vertex.index] == binding.CONSTRAINT_RAIL_LINE:
                constraint_modes.append(binding.CONSTRAINT_RAIL_LINE)
            elif self.normal_only:
                constraint_modes.append(binding.CONSTRAINT_NORMAL_ONLY)
            else:
                constraint_modes.append(binding.CONSTRAINT_FREE)
            if constraint_modes[-1] == binding.CONSTRAINT_RAIL_LINE:
                directions.extend(rail_directions[vertex.index])
            else:
                normal = vertex.normal.normalized() if vertex.normal.length_squared > 0.0 else Vector((0.0, 0.0, 1.0))
                directions.extend(normal)
        if all(mode == binding.CONSTRAINT_FIXED for mode in constraint_modes):
            self.report({"WARNING"}, "境界固定後に移動可能な選択頂点がありません")
            return {"CANCELLED"}

        closed_mesh = _is_closed_mesh(bm)
        triangles = []
        volume_correction = 0.0
        if self.preserve_volume and closed_mesh:
            bmesh.update_edit_mesh(mesh, loop_triangles=True, destructive=False)
            mesh.calc_loop_triangles()
            triangles = [index for triangle in mesh.loop_triangles for index in triangle.vertices]
            volume_correction = 1.0

        try:
            result = binding.smooth(
                positions,
                edges,
                mode=_MODE_VALUES[self.mode],
                iterations=self.iterations,
                strength=self.strength,
                taubin_mu=self.taubin_mu,
                hc_alpha=self.hc_alpha,
                hc_beta=self.hc_beta,
                volume_correction=volume_correction,
                triangles=triangles,
                vertex_weights=weights,
                constraint_modes=constraint_modes,
                constraint_directions=directions,
            )
        except (FileNotFoundError, ValueError, binding.MeshSmoothingError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}

        for vertex in bm.verts:
            start = vertex.index * 3
            vertex.co = result[start : start + 3]
        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
        if self.preserve_volume and not closed_mesh:
            self.report({"INFO"}, "開メッシュのため体積補正を省略し、選択方式だけを適用しました")
        return {"FINISHED"}


class YWTA_OT_volume_smooth_brush(Operator):
    """1ストローク単位で実行するジオデシックスムージングブラシ。"""

    bl_idname = "ywta.volume_smooth_brush"
    bl_label = "Volume Smooth Brush"
    bl_description = "表面距離falloffを使い、ブラシ範囲をリアルタイムにスムージングします"
    bl_options = {"REGISTER", "UNDO", "BLOCKING"}

    brush_mode: EnumProperty(name="ブラシ", items=_BRUSH_MODE_ITEMS, default="SMOOTH")
    radius: FloatProperty(name="半径", default=0.25, min=0.0001, soft_max=10.0, subtype="DISTANCE")
    strength: FloatProperty(name="強さ", default=0.5, min=0.0, max=1.0, subtype="FACTOR")
    iterations: IntProperty(name="dab反復回数", default=1, min=1, max=10)
    spacing: FloatProperty(name="間隔", default=0.15, min=0.01, max=1.0, subtype="FACTOR")
    use_selection_mask: BoolProperty(
        name="選択範囲をマスク",
        description="選択頂点の内側だけをブラシ対象にします",
        default=False,
    )
    preserve_boundary: BoolProperty(
        name="境界を固定",
        description="開境界と、選択マスク使用時の選択境界を固定します",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None
            and obj.type == "MESH"
            and obj.mode == "EDIT"
            and context.area is not None
            and context.area.type == "VIEW_3D"
            and context.region is not None
            and context.region.type == "WINDOW"
            and context.region_data is not None
        )

    def invoke(self, context, event):
        obj = context.active_object
        mesh = obj.data
        bm = bmesh.from_edit_mesh(mesh)
        bm.verts.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        bm.verts.index_update()
        bm.faces.index_update()
        bm.normal_update()
        if not bm.faces:
            self.report({"WARNING"}, "面を持つメッシュで実行してください")
            return {"CANCELLED"}

        self._object = obj
        self._mesh = mesh
        self._bm = bm
        self._initial_positions = [vertex.co.copy() for vertex in bm.verts]
        self._closed_mesh = _is_closed_mesh(bm)
        edges = [index for edge in bm.edges for index in (edge.verts[0].index, edge.verts[1].index)]
        triangles = []
        if self._closed_mesh:
            bmesh.update_edit_mesh(mesh, loop_triangles=True, destructive=False)
            mesh.calc_loop_triangles()
            triangles = [index for triangle in mesh.loop_triangles for index in triangle.vertices]
        self._session = binding.MeshSmoothingSession(len(bm.verts), edges, triangles)
        self._bvh = BVHTree.FromBMesh(bm)
        self._stroke_active = False
        self._adjust_mode = None
        self._last_dab_world = None
        self._hit_world = None
        self._draw_handle = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_brush,
            (),
            "WINDOW",
            "POST_PIXEL",
        )
        context.window_manager.modal_handler_add(self)
        self._update_status(context)
        context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if context.area:
            context.area.tag_redraw()
        if event.type in {"ESC", "RIGHTMOUSE"}:
            self._restore_initial()
            self._cleanup(context)
            return {"CANCELLED"}
        if event.type == "LEFTMOUSE" and event.value == "RELEASE" and self._stroke_active:
            self._cleanup(context)
            return {"FINISHED"}
        if event.type in {"ONE", "TWO", "THREE"} and event.value == "PRESS":
            self.brush_mode = {"ONE": "SMOOTH", "TWO": "VOLUME", "THREE": "BUMPS"}[event.type]
            self._update_status(context)
            return {"RUNNING_MODAL"}
        if event.type in {"M", "B"} and event.value == "PRESS":
            if event.type == "M":
                self.use_selection_mask = not self.use_selection_mask
            else:
                self.preserve_boundary = not self.preserve_boundary
            self._update_status(context)
            return {"RUNNING_MODAL"}
        if event.type == "F":
            if event.value == "PRESS":
                self._adjust_mode = "STRENGTH" if event.shift else "RADIUS"
                self._adjust_start_x = event.mouse_region_x
                self._adjust_start_value = self.strength if event.shift else self.radius
            elif event.value == "RELEASE":
                self._adjust_mode = None
            return {"RUNNING_MODAL"}
        if event.type in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"} and event.value == "PRESS":
            delta = 1 if event.type == "WHEELUPMOUSE" else -1
            self.iterations = max(1, min(10, self.iterations + delta))
            self._update_status(context)
            return {"RUNNING_MODAL"}
        if event.type in {"MOUSEMOVE", "LEFTMOUSE"}:
            if self._adjust_mode is not None:
                delta = event.mouse_region_x - self._adjust_start_x
                if self._adjust_mode == "RADIUS":
                    self.radius = max(0.0001, self._adjust_start_value * (2.0 ** (delta / 100.0)))
                else:
                    self.strength = max(0.01, min(1.0, self._adjust_start_value + delta / 200.0))
                self._update_status(context)
                return {"RUNNING_MODAL"}
            hit = self._ray_hit(context, event)
            self._hit_world = hit[1] if hit else None
            if event.type == "LEFTMOUSE" and event.value == "PRESS":
                self._stroke_active = True
            if self._stroke_active and hit and self._needs_dab(hit[1]):
                try:
                    self._apply_dab(hit[0], hit[2])
                except (ValueError, binding.MeshSmoothingError) as error:
                    self.report({"ERROR"}, str(error))
                    self._restore_initial()
                    self._cleanup(context)
                    return {"CANCELLED"}
            return {"RUNNING_MODAL"}
        return {"RUNNING_MODAL"}

    def _update_status(self, context):
        """現在のプリセットと主要ショートカットをステータスバーへ表示する。"""
        labels = {"SMOOTH": "Smooth", "VOLUME": "Volume", "BUMPS": "Remove Bumps"}
        context.workspace.status_text_set(
            f"{labels[self.brush_mode]} | LMB: Stroke | F: Radius {self.radius:.3g} | "
            f"Shift+F: Strength {self.strength:.2f} | Wheel: Iter {self.iterations} | "
            f"1/2/3: Mode | M: Mask | B: Boundary | Esc/RMB: Cancel"
        )

    def _ray_hit(self, context, event):
        """マウス位置からローカルメッシュへray castする。"""
        coordinate = (event.mouse_region_x, event.mouse_region_y)
        origin_world = view3d_utils.region_2d_to_origin_3d(context.region, context.region_data, coordinate)
        direction_world = view3d_utils.region_2d_to_vector_3d(context.region, context.region_data, coordinate)
        inverse = self._object.matrix_world.inverted_safe()
        origin_local = inverse @ origin_world
        direction_local = (inverse.to_3x3() @ direction_world).normalized()
        location, _normal, face_index, _distance = self._bvh.ray_cast(origin_local, direction_local)
        if location is None or face_index is None:
            return None
        return location, self._object.matrix_world @ location, face_index

    def _needs_dab(self, hit_world):
        """ブラシ間隔を満たす場合だけdabを許可する。"""
        if self._last_dab_world is None:
            return True
        return (hit_world - self._last_dab_world).length >= self.radius * self.spacing

    def _apply_dab(self, hit_local, face_index):
        """現在のヒット位置へ1回のRustスムージングを適用する。"""
        bm = self._bm
        weights = _geodesic_brush_weights(
            bm,
            face_index,
            hit_local,
            self._object.matrix_world,
            self.radius,
            self.strength,
            self.use_selection_mask,
            self.preserve_boundary,
        )
        if not any(weight > 0.0 for weight in weights):
            return
        _apply_brush_solver(
            bm,
            self._session,
            weights,
            self.brush_mode,
            self._closed_mesh,
            self.iterations,
        )
        bmesh.update_edit_mesh(self._mesh, loop_triangles=False, destructive=False)
        self._bvh = BVHTree.FromBMesh(bm)
        self._last_dab_world = self._object.matrix_world @ hit_local

    def _draw_brush(self):
        """ヒット位置へブラシ半径の円を描画する。"""
        if self._hit_world is None:
            return
        context = bpy.context
        center = view3d_utils.location_3d_to_region_2d(context.region, context.region_data, self._hit_world)
        if center is None:
            return
        view_right = context.region_data.view_matrix.inverted().to_3x3() @ Vector((1.0, 0.0, 0.0))
        edge = view3d_utils.location_3d_to_region_2d(
            context.region,
            context.region_data,
            self._hit_world + view_right.normalized() * self.radius,
        )
        if edge is None:
            return
        pixel_radius = max(2.0, (edge - center).length)
        points = [
            (
                center.x + math.cos(index * math.tau / 48) * pixel_radius,
                center.y + math.sin(index * math.tau / 48) * pixel_radius,
            )
            for index in range(49)
        ]
        import gpu
        from gpu_extras.batch import batch_for_shader

        shader = gpu.shader.from_builtin("UNIFORM_COLOR")
        batch = batch_for_shader(shader, "LINE_STRIP", {"pos": points})
        shader.bind()
        colors = {
            "SMOOTH": (0.35, 0.8, 1.0, 1.0),
            "VOLUME": (0.3, 1.0, 0.45, 1.0),
            "BUMPS": (0.8, 0.45, 1.0, 1.0),
        }
        color = colors[self.brush_mode] if not self._stroke_active else (1.0, 0.55, 0.15, 1.0)
        shader.uniform_float("color", color)
        batch.draw(shader)

    def _restore_initial(self):
        """キャンセル時にストローク開始位置へ戻す。"""
        for vertex, position in zip(self._bm.verts, self._initial_positions):
            vertex.co = position
        self._bm.normal_update()
        bmesh.update_edit_mesh(self._mesh, loop_triangles=False, destructive=False)

    def _cleanup(self, context):
        """draw handlerとステータス表示を確実に解除する。"""
        if getattr(self, "_draw_handle", None) is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._draw_handle, "WINDOW")
            self._draw_handle = None
        context.workspace.status_text_set(None)
        if context.area:
            context.area.tag_redraw()


def menu_func(self, _context):
    """頂点コンテキストメニューへオペレータを追加する。"""
    self.layout.operator(YWTA_OT_volume_smooth.bl_idname)
    self.layout.operator(YWTA_OT_volume_smooth_brush.bl_idname, icon="BRUSH_SMOOTH")


classes = [YWTA_OT_volume_smooth, YWTA_OT_volume_smooth_brush]


def register():
    """Blenderへクラスとメニューを登録する。"""
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.VIEW3D_MT_edit_mesh_vertices.append(menu_func)


def unregister():
    """Blenderからクラスとメニューを解除する。"""
    bpy.types.VIEW3D_MT_edit_mesh_vertices.remove(menu_func)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
