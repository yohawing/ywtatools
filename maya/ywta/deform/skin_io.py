"""Maya スキンウェイトを検証可能な JSON として保存・復元する。"""

from __future__ import absolute_import

import hashlib
import json
import math
import os
import re
import struct
import tempfile

import maya.api.OpenMaya as om
import maya.api.OpenMayaAnim as oma
import maya.cmds as cmds

from ywta.deform import skin_weight_command
from ywta.core import undo_utils


FORMAT = "ywta.skin_weights"
VERSION = 1
WEIGHT_EPSILON = 1.0e-8
TEMP_SKIN_FILENAME = "ywta_temp_skin_weights.json"


def _mesh_shape(mesh):
    """メッシュ名を一意な非 intermediate shape のロングパスへ解決する。"""
    matches = cmds.ls(mesh, long=True) or []
    if len(matches) != 1:
        raise ValueError("メッシュを一意に解決できません: {}".format(mesh))
    node = matches[0]
    if cmds.nodeType(node) == "mesh":
        if cmds.getAttr(node + ".intermediateObject"):
            raise ValueError("intermediate shape は対象にできません: {}".format(node))
        return node
    shapes = cmds.listRelatives(node, shapes=True, noIntermediate=True, fullPath=True, type="mesh") or []
    if len(shapes) != 1:
        raise ValueError("非 intermediate mesh shape を1つだけ指定してください: {}".format(mesh))
    return shapes[0]


def _dag_path(node):
    """ノードの MDagPath を取得する。"""
    selection = om.MSelectionList()
    selection.add(node)
    return selection.getDagPath(0)


def _depend_node(node):
    """ノードの MObject を取得する。"""
    selection = om.MSelectionList()
    selection.add(node)
    return selection.getDependNode(0)


def _skin_cluster(shape):
    """shape に接続された skinCluster を一意に取得する。"""
    clusters = cmds.ls(cmds.listHistory(shape, pruneDagObjects=True) or [], type="skinCluster") or []
    clusters = list(dict.fromkeys(clusters))
    if not clusters:
        return None
    if len(clusters) != 1:
        raise ValueError("skinCluster が複数あります: {}".format(shape))
    return clusters[0]


def _vertex_component(vertex_count):
    """全頂点を含むコンポーネントを作る。"""
    component = om.MFnSingleIndexedComponent().create(om.MFn.kMeshVertComponent)
    om.MFnSingleIndexedComponent(component).addElements(range(vertex_count))
    return component


def _topology(fn_mesh):
    """頂点順とポリゴン接続を検証する fingerprint を作る。"""
    face_counts, face_connects = fn_mesh.getVertices()
    return _topology_from_data(fn_mesh.numVertices, fn_mesh.numPolygons, face_counts, face_connects)


def _topology_from_data(vertex_count, polygon_count, face_counts, face_connects):
    """flat topology data から fingerprint を作る。"""
    digest = hashlib.sha256()
    for value in [vertex_count, polygon_count] + list(face_counts) + list(face_connects):
        digest.update(struct.pack("<q", int(value)))
    return {
        "vertex_count": int(vertex_count),
        "polygon_count": int(polygon_count),
        "sha256": digest.hexdigest(),
    }


def _geometry(fn_mesh):
    """transfer source 再構築用の world-space geometry を取得する。"""
    face_counts, face_connects = fn_mesh.getVertices()
    points = fn_mesh.getPoints(om.MSpace.kWorld)
    return {
        "points": [[float(point.x), float(point.y), float(point.z)] for point in points],
        "face_counts": list(face_counts),
        "face_connects": list(face_connects),
    }


def capture(mesh):
    """スキンウェイトをシリアライズ可能な辞書へ変換する。

    Args:
        mesh: スキンされた mesh transform または shape。

    Returns:
        バージョン付きスキンウェイト辞書。
    """
    shape = _mesh_shape(mesh)
    cluster = _skin_cluster(shape)
    if not cluster:
        raise ValueError("skinCluster が見つかりません: {}".format(shape))

    mesh_path = _dag_path(shape)
    fn_mesh = om.MFnMesh(mesh_path)
    fn_skin = oma.MFnSkinCluster(_depend_node(cluster))
    influence_paths = fn_skin.influenceObjects()
    weights, influence_count = fn_skin.getWeights(mesh_path, _vertex_component(fn_mesh.numVertices))

    rows = []
    for vertex_index in range(fn_mesh.numVertices):
        offset = vertex_index * influence_count
        row = []
        for influence_index in range(influence_count):
            value = float(weights[offset + influence_index])
            if value > WEIGHT_EPSILON:
                row.append([influence_index, value])
        rows.append(row)

    influences = []
    for path in influence_paths:
        full_path = path.fullPathName()
        leaf = full_path.rsplit("|", 1)[-1]
        influences.append({"name": leaf, "path": full_path})

    return {
        "format": FORMAT,
        "version": VERSION,
        "scene": {
            "linear_unit": cmds.currentUnit(query=True, linear=True),
            "up_axis": cmds.upAxis(query=True, axis=True),
        },
        "mesh": {
            "name": shape.rsplit("|", 1)[-1],
            "topology": _topology(fn_mesh),
            "geometry": _geometry(fn_mesh),
        },
        "influences": influences,
        "weights": rows,
    }


def save(mesh, file_path):
    """スキンウェイトを JSON へ原子的に保存する。"""
    data = capture(mesh)
    target = os.path.abspath(file_path)
    directory = os.path.dirname(target)
    if not os.path.isdir(directory):
        raise ValueError("保存先ディレクトリがありません: {}".format(directory))
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=directory, prefix=".ywta_skin_", suffix=".tmp", delete=False
    )
    temporary = handle.name
    try:
        with handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, target)
    except Exception:
        if os.path.exists(temporary):
            os.remove(temporary)
        raise
    return target


def _validate_data(data):
    """外部 JSON を Maya に触れる前に検証する。"""
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError("YWTA Skin IO ファイルではありません。")
    if data.get("version") != VERSION:
        raise ValueError("未対応の Skin IO version です: {}".format(data.get("version")))
    scene = data.get("scene")
    if scene is not None and (
        not isinstance(scene, dict)
        or not isinstance(scene.get("linear_unit"), str)
        or not scene["linear_unit"]
        or scene.get("up_axis") not in {"y", "z"}
    ):
        raise ValueError("scene conventionが不正です。")
    mesh = data.get("mesh")
    topology = mesh.get("topology") if isinstance(mesh, dict) else None
    if not isinstance(topology, dict):
        raise ValueError("mesh.topology がありません。")
    vertex_count = topology.get("vertex_count")
    if not isinstance(vertex_count, int) or isinstance(vertex_count, bool) or vertex_count < 1:
        raise ValueError("vertex_count が不正です。")
    digest = topology.get("sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError("topology sha256 が不正です。")
    polygon_count = topology.get("polygon_count")
    if not isinstance(polygon_count, int) or isinstance(polygon_count, bool) or polygon_count < 1:
        raise ValueError("polygon_count が不正です。")

    geometry = mesh.get("geometry")
    if geometry is not None:
        if not isinstance(geometry, dict):
            raise ValueError("mesh.geometry が不正です。")
        points = geometry.get("points")
        face_counts = geometry.get("face_counts")
        face_connects = geometry.get("face_connects")
        if not isinstance(points, list) or len(points) != vertex_count:
            raise ValueError("geometry points の頂点数が一致しません。")
        for point in points:
            if (
                not isinstance(point, list)
                or len(point) != 3
                or any(
                    not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value)
                    for value in point
                )
            ):
                raise ValueError("geometry point が不正です。")
        if (
            not isinstance(face_counts, list)
            or len(face_counts) != polygon_count
            or any(not isinstance(value, int) or isinstance(value, bool) or value < 3 for value in face_counts)
        ):
            raise ValueError("geometry face_counts が不正です。")
        if (
            not isinstance(face_connects, list)
            or sum(face_counts) != len(face_connects)
            or any(
                not isinstance(value, int) or isinstance(value, bool) or value < 0 or value >= vertex_count
                for value in face_connects
            )
        ):
            raise ValueError("geometry face_connects が不正です。")
        geometry_topology = _topology_from_data(vertex_count, polygon_count, face_counts, face_connects)
        if geometry_topology != topology:
            raise ValueError("geometry と topology fingerprint が一致しません。")

    influences = data.get("influences")
    if not isinstance(influences, list) or not influences:
        raise ValueError("influences がありません。")
    influence_keys = set()
    for influence in influences:
        if (
            not isinstance(influence, dict)
            or not isinstance(influence.get("name"), str)
            or not isinstance(influence.get("path"), str)
        ):
            raise ValueError("influence が不正です。")
        key = (influence.get("path"), influence["name"])
        if key in influence_keys:
            raise ValueError("influence が重複しています: {}".format(influence["name"]))
        influence_keys.add(key)

    rows = data.get("weights")
    if not isinstance(rows, list) or len(rows) != vertex_count:
        raise ValueError("weights の頂点数が一致しません。")
    influence_count = len(influences)
    for vertex_index, row in enumerate(rows):
        if not isinstance(row, list) or not row:
            raise ValueError("頂点 {} に有効なウェイトがありません。".format(vertex_index))
        seen = set()
        total = 0.0
        for entry in row:
            if not isinstance(entry, list) or len(entry) != 2:
                raise ValueError("頂点 {} のウェイト形式が不正です。".format(vertex_index))
            index, value = entry
            if not isinstance(index, int) or isinstance(index, bool) or index < 0 or index >= influence_count or index in seen:
                raise ValueError("頂点 {} の influence index が不正です。".format(vertex_index))
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value < 0:
                raise ValueError("頂点 {} のウェイト値が不正です。".format(vertex_index))
            seen.add(index)
            total += value
        if total <= WEIGHT_EPSILON:
            raise ValueError("頂点 {} のウェイト合計が0です。".format(vertex_index))
    return data


def read(file_path):
    """Skin IO JSON を読み込み、完全検証した辞書を返す。"""
    with open(file_path, "r", encoding="utf-8") as handle:
        return _validate_data(json.load(handle))


def _base_name(name):
    """DAG パスと namespace を除いた名前を返す。"""
    return name.rsplit("|", 1)[-1].rsplit(":", 1)[-1]


def _resolve_influences(saved):
    """保存済み influence を scene joint へ曖昧性なしで対応付ける。"""
    scene_joints = cmds.ls(type="joint", long=True) or []
    result = []
    resolved_ids = set()
    missing = []
    for influence in saved:
        path = influence.get("path")
        if isinstance(path, str) and cmds.objExists(path) and cmds.nodeType(path) == "joint":
            resolved = cmds.ls(path, long=True)[0]
        else:
            name = influence["name"]
            exact = [joint for joint in scene_joints if joint.rsplit("|", 1)[-1] == name]
            candidates = exact or [joint for joint in scene_joints if _base_name(joint) == _base_name(name)]
            if len(candidates) == 1:
                resolved = candidates[0]
            elif len(candidates) > 1:
                raise ValueError("influence 名が曖昧です: {}".format(name))
            else:
                missing.append(name)
                continue
        node_uuid = (cmds.ls(resolved, uuid=True) or [None])[0]
        if node_uuid in resolved_ids:
            raise ValueError("複数の保存influenceが同じjointへ解決されました: {}".format(resolved))
        resolved_ids.add(node_uuid)
        result.append(resolved)
    if missing:
        raise ValueError("scene に influence がありません: {}".format(", ".join(missing)))
    return result


def _ensure_topology(shape, saved_topology):
    """Direct load 対象の頂点順・接続が保存時と同一か検証する。"""
    current = _topology(om.MFnMesh(_dag_path(shape)))
    if current != saved_topology:
        raise ValueError(
            "トポロジーが一致しません。saved={} current={}".format(saved_topology.get("sha256"), current.get("sha256"))
        )


def _ensure_skin_cluster(shape, influences):
    """必要な influence を持つ skinCluster を取得または作成する。"""
    cluster = _skin_cluster(shape)
    if cluster is None:
        transform = cmds.listRelatives(shape, parent=True, fullPath=True)[0]
        return cmds.skinCluster(influences, transform, toSelectedBones=True, normalizeWeights=1)[0]
    existing = cmds.skinCluster(cluster, query=True, influence=True) or []
    existing_paths = set(cmds.ls(existing, long=True) or [])
    for influence in influences:
        if influence not in existing_paths:
            cmds.skinCluster(cluster, edit=True, addInfluence=influence, weight=0.0)
    return cluster


def _vertex_indices(values, vertex_count):
    """部分適用する頂点indexを順序保持して検証する。"""
    if isinstance(values, (str, bytes)):
        raise ValueError("vertex_indicesは整数列にしてください。")
    try:
        result = list(values)
    except TypeError as error:
        raise ValueError("vertex_indicesは整数列にしてください。") from error
    if not result:
        raise ValueError("vertex_indicesが空です。")
    if any(not isinstance(index, int) or isinstance(index, bool) for index in result):
        raise ValueError("vertex indexは整数にしてください。")
    if len(set(result)) != len(result):
        raise ValueError("vertex indexが重複しています。")
    if any(index < 0 or index >= vertex_count for index in result):
        raise ValueError("vertex indexが範囲外です。")
    return result


def _write_weights(shape, cluster, influences, data, vertex_indices=None):
    """検証済み sparse weights を skinCluster へ一括設定する。"""
    fn_skin = oma.MFnSkinCluster(_depend_node(cluster))
    physical_paths = [path.fullPathName() for path in fn_skin.influenceObjects()]
    physical_by_path = {path: index for index, path in enumerate(physical_paths)}
    physical_indices = [physical_by_path[influence] for influence in influences]

    vertex_count = data["mesh"]["topology"]["vertex_count"]
    indices = range(vertex_count) if vertex_indices is None else vertex_indices
    dense = om.MDoubleArray([0.0] * (len(indices) * len(physical_paths)))
    for row_index, vertex_index in enumerate(indices):
        row = data["weights"][vertex_index]
        total = sum(float(entry[1]) for entry in row)
        for saved_index, value in row:
            physical_index = physical_indices[saved_index]
            dense[row_index * len(physical_paths) + physical_index] = float(value) / total

    skin_weight_command.execute(
        cluster,
        shape,
        indices,
        range(len(physical_paths)),
        dense,
        normalize=True,
    )


def _normalize_influence_subset(shape, cluster, influences):
    """保存外 influence を0にし、転送結果を保存 influence 内で正規化する。"""
    fn_skin = oma.MFnSkinCluster(_depend_node(cluster))
    physical_paths = [path.fullPathName() for path in fn_skin.influenceObjects()]
    included = {physical_paths.index(influence) for influence in influences}
    vertex_count = om.MFnMesh(_dag_path(shape)).numVertices
    component = _vertex_component(vertex_count)
    weights, influence_count = fn_skin.getWeights(_dag_path(shape), component)
    dense = om.MDoubleArray([0.0] * len(weights))
    for vertex_index in range(vertex_count):
        offset = vertex_index * influence_count
        total = sum(float(weights[offset + index]) for index in included)
        if total <= WEIGHT_EPSILON:
            raise RuntimeError("転送後の頂点 {} に有効な influence weight がありません。".format(vertex_index))
        for index in included:
            dense[offset + index] = float(weights[offset + index]) / total
    skin_weight_command.execute(
        cluster,
        shape,
        range(vertex_count),
        range(influence_count),
        dense,
        normalize=True,
    )


def apply(mesh, data):
    """検証済みデータを同一トポロジーのメッシュへ適用する。"""
    data = _validate_data(data)
    shape = _mesh_shape(mesh)
    _ensure_topology(shape, data["mesh"]["topology"])
    influences = _resolve_influences(data["influences"])

    undo_utils.require_enabled("Skin IO Load")
    cmds.undoInfo(openChunk=True, chunkName="YWTA Skin IO Load")
    failed = False
    try:
        cluster = _ensure_skin_cluster(shape, influences)
        _write_weights(shape, cluster, influences, data)
    except Exception:
        failed = True
        raise
    finally:
        cmds.undoInfo(closeChunk=True)
        if failed:
            cmds.undo()
    return cluster


def load(mesh, file_path):
    """JSON を読み込み、同一トポロジーのメッシュへ適用する。"""
    return apply(mesh, read(file_path))


def apply_subset(mesh, data, vertex_indices):
    """同一トポロジーmeshの指定頂点だけへ検証済みweightsを適用する。"""
    data = _validate_data(data)
    shape = _mesh_shape(mesh)
    _ensure_topology(shape, data["mesh"]["topology"])
    indices = _vertex_indices(
        vertex_indices,
        data["mesh"]["topology"]["vertex_count"],
    )
    influences = _resolve_influences(data["influences"])
    if _skin_cluster(shape) is None:
        raise ValueError("部分適用には既存skinClusterが必要です: {}".format(shape))

    undo_utils.require_enabled("Skin IO Load Subset")
    cmds.undoInfo(openChunk=True, chunkName="YWTA Skin IO Load Subset")
    failed = False
    try:
        cluster = _ensure_skin_cluster(shape, influences)
        _write_weights(
            shape,
            cluster,
            influences,
            data,
            vertex_indices=indices,
        )
    except Exception:
        failed = True
        raise
    finally:
        cmds.undoInfo(closeChunk=True)
        if failed:
            cmds.undo()
    return cluster


def load_subset(mesh, file_path, vertex_indices):
    """JSONを読み込み、同一トポロジーmeshの指定頂点だけへ適用する。"""
    return apply_subset(mesh, read(file_path), vertex_indices)


def temp_skin_path():
    """Mayaユーザー用の一時Skin IO JSONパスを返す。"""
    return os.path.join(cmds.internalVar(userAppDir=True), TEMP_SKIN_FILENAME)


def save_temp(mesh, file_path=None):
    """mesh weightsを固定または指定の一時JSONへ保存する。"""
    return save(mesh, file_path or temp_skin_path())


def load_temp(mesh, file_path=None, transfer_mode=False):
    """一時JSONをDirectまたはclosest-point Transferで適用する。"""
    if not isinstance(transfer_mode, bool):
        raise ValueError("transfer_modeはboolにしてください。")
    data = read(file_path or temp_skin_path())
    if transfer_mode:
        return transfer(mesh, data)
    return apply(mesh, data)


def _create_transfer_source(geometry):
    """保存 geometry から一時 source mesh を再構築する。"""
    transform = cmds.createNode("transform", name="__ywtaSkinTransferSource#")
    parent = _depend_node(transform)
    points = [om.MPoint(*point) for point in geometry["points"]]
    om.MFnMesh().create(
        points,
        geometry["face_counts"],
        geometry["face_connects"],
        parent=parent,
    )
    shape = cmds.listRelatives(transform, shapes=True, noIntermediate=True, fullPath=True, type="mesh")[0]
    return transform, shape


def _ensure_transfer_convention(data):
    """world-space geometryのscene convention一致を検証する。"""
    saved = data.get("scene")
    if saved is None:
        return
    current = {
        "linear_unit": cmds.currentUnit(query=True, linear=True),
        "up_axis": cmds.upAxis(query=True, axis=True),
    }
    mismatches = [key for key in ("linear_unit", "up_axis") if saved[key] != current[key]]
    if mismatches:
        raise ValueError("Skin Transfer scene conventionが一致しません: saved={} current={}".format(saved, current))


def transfer(mesh, data, surface_association="closestPoint"):
    """保存 source を再構築し、異なる topology の target へ weights を転送する。"""
    data = _validate_data(data)
    if surface_association not in {"closestPoint", "rayCast", "closestComponent"}:
        raise ValueError("未対応の surface association です: {}".format(surface_association))
    geometry = data["mesh"].get("geometry")
    if geometry is None:
        raise ValueError("この Skin IO ファイルには transfer geometry がありません。")
    _ensure_transfer_convention(data)
    target_shape = _mesh_shape(mesh)
    influences = _resolve_influences(data["influences"])

    undo_utils.require_enabled("Skin IO Transfer")
    cmds.undoInfo(openChunk=True, chunkName="YWTA Skin IO Transfer")
    failed = False
    temporary = None
    try:
        temporary, source_shape = _create_transfer_source(geometry)
        source_cluster = _ensure_skin_cluster(source_shape, influences)
        _write_weights(source_shape, source_cluster, influences, data)
        target_cluster = _ensure_skin_cluster(target_shape, influences)
        cmds.copySkinWeights(
            sourceSkin=source_cluster,
            destinationSkin=target_cluster,
            noMirror=True,
            surfaceAssociation=surface_association,
            influenceAssociation=["name", "oneToOne"],
            normalize=True,
        )
        _normalize_influence_subset(target_shape, target_cluster, influences)
    except Exception:
        failed = True
        raise
    finally:
        try:
            if temporary and cmds.objExists(temporary):
                try:
                    cmds.delete(temporary)
                except Exception:
                    failed = True
                    raise
        finally:
            cmds.undoInfo(closeChunk=True)
            if failed:
                cmds.undo()
    return target_cluster


def load_transfer(mesh, file_path, surface_association="closestPoint"):
    """JSON を読み込み、異なる topology の target へ weights を転送する。"""
    return transfer(mesh, read(file_path), surface_association=surface_association)


def save_selected():
    """選択メッシュをファイルダイアログ経由で保存する。"""
    selected = cmds.ls(selection=True, long=True) or []
    if len(selected) != 1:
        raise ValueError("保存するメッシュを1つ選択してください。")
    paths = cmds.fileDialog2(fileMode=0, dialogStyle=2, caption="Save Skin Weights", fileFilter="JSON (*.json)")
    if not paths:
        return None
    return save(selected[0], paths[0])


def save_temp_selected():
    """選択meshをMayaユーザー用の一時Skin IO JSONへ保存する。"""
    selected = cmds.ls(selection=True, long=True) or []
    if len(selected) != 1:
        raise ValueError("一時保存するメッシュを1つ選択してください。")
    path = save_temp(selected[0])
    cmds.inViewMessage(
        statusMessage="Saved temporary skin weights.",
        position="topCenter",
        fade=True,
    )
    return path


def load_selected():
    """選択メッシュへファイルダイアログ経由で復元する。"""
    selected = cmds.ls(selection=True, long=True) or []
    if len(selected) != 1:
        raise ValueError("復元先メッシュを1つ選択してください。")
    paths = cmds.fileDialog2(fileMode=1, dialogStyle=2, caption="Load Skin Weights", fileFilter="JSON (*.json)")
    if not paths:
        return None
    return load(selected[0], paths[0])


def _selected_vertex_target():
    """現在選択から単一meshとflatten済み頂点indexを返す。"""
    components = cmds.filterExpand(
        cmds.ls(selection=True, long=True) or [],
        selectionMask=31,
        expand=True,
    ) or []
    if not components:
        raise ValueError("復元先のmesh頂点を1つ以上選択してください。")
    shapes = []
    indices = []
    for component in components:
        match = re.match(r"^(.*)\.vtx\[(\d+)\]$", component)
        if not match:
            raise ValueError("mesh頂点だけを選択してください: {}".format(component))
        shape = _mesh_shape(match.group(1))
        if shape not in shapes:
            shapes.append(shape)
        indices.append(int(match.group(2)))
    if len(shapes) != 1:
        raise ValueError("1つのmesh上の頂点だけを選択してください。")
    return shapes[0], indices


def load_selected_subset():
    """選択頂点へ同一トポロジーSkin IO JSONを部分適用する。"""
    mesh, indices = _selected_vertex_target()
    paths = cmds.fileDialog2(
        fileMode=1,
        dialogStyle=2,
        caption="Load Skin Weights to Selected Vertices",
        fileFilter="JSON (*.json)",
    )
    if not paths:
        return None
    return load_subset(mesh, paths[0], indices)


def load_temp_selected(transfer_mode=False):
    """選択meshへMayaユーザー用の一時Skin IO JSONを適用する。"""
    selected = cmds.ls(selection=True, long=True) or []
    if len(selected) != 1:
        raise ValueError("一時ウェイトの適用先メッシュを1つ選択してください。")
    return load_temp(selected[0], transfer_mode=transfer_mode)


def load_selected_transfer():
    """選択メッシュへ closest-point でスキンウェイトを転送する。"""
    selected = cmds.ls(selection=True, long=True) or []
    if len(selected) != 1:
        raise ValueError("転送先メッシュを1つ選択してください。")
    paths = cmds.fileDialog2(
        fileMode=1,
        dialogStyle=2,
        caption="Transfer Skin Weights",
        fileFilter="JSON (*.json)",
    )
    if not paths:
        return None
    return load_transfer(selected[0], paths[0])
