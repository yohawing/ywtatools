"""Maya スキンウェイトを検証可能な JSON として保存・復元する。"""

from __future__ import absolute_import

import hashlib
import json
import math
import os
import struct
import tempfile

import maya.api.OpenMaya as om
import maya.api.OpenMayaAnim as oma
import maya.cmds as cmds


FORMAT = "ywta.skin_weights"
VERSION = 1
WEIGHT_EPSILON = 1.0e-8


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
    digest = hashlib.sha256()
    for value in [fn_mesh.numVertices, fn_mesh.numPolygons] + list(face_counts) + list(face_connects):
        digest.update(struct.pack("<q", int(value)))
    return {
        "vertex_count": fn_mesh.numVertices,
        "polygon_count": fn_mesh.numPolygons,
        "sha256": digest.hexdigest(),
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
        "mesh": {
            "name": shape.rsplit("|", 1)[-1],
            "topology": _topology(fn_mesh),
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
    missing = []
    for influence in saved:
        path = influence.get("path")
        if isinstance(path, str) and cmds.objExists(path) and cmds.nodeType(path) == "joint":
            result.append(cmds.ls(path, long=True)[0])
            continue
        name = influence["name"]
        exact = [joint for joint in scene_joints if joint.rsplit("|", 1)[-1] == name]
        candidates = exact or [joint for joint in scene_joints if _base_name(joint) == _base_name(name)]
        if len(candidates) == 1:
            result.append(candidates[0])
        elif len(candidates) > 1:
            raise ValueError("influence 名が曖昧です: {}".format(name))
        else:
            missing.append(name)
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


def apply(mesh, data):
    """検証済みデータを同一トポロジーのメッシュへ適用する。"""
    data = _validate_data(data)
    shape = _mesh_shape(mesh)
    _ensure_topology(shape, data["mesh"]["topology"])
    influences = _resolve_influences(data["influences"])

    cmds.undoInfo(openChunk=True, chunkName="YWTA Skin IO Load")
    failed = False
    try:
        cluster = _skin_cluster(shape)
        if cluster is None:
            transform = cmds.listRelatives(shape, parent=True, fullPath=True)[0]
            cluster = cmds.skinCluster(influences, transform, toSelectedBones=True, normalizeWeights=1)[0]
        else:
            existing = cmds.skinCluster(cluster, query=True, influence=True) or []
            existing_paths = set(cmds.ls(existing, long=True) or [])
            for influence in influences:
                if influence not in existing_paths:
                    cmds.skinCluster(cluster, edit=True, addInfluence=influence, weight=0.0)

        fn_skin = oma.MFnSkinCluster(_depend_node(cluster))
        physical_paths = [path.fullPathName() for path in fn_skin.influenceObjects()]
        physical_by_path = {path: index for index, path in enumerate(physical_paths)}
        physical_indices = [physical_by_path[influence] for influence in influences]

        vertex_count = data["mesh"]["topology"]["vertex_count"]
        dense = om.MDoubleArray([0.0] * (vertex_count * len(physical_paths)))
        for vertex_index, row in enumerate(data["weights"]):
            total = sum(float(entry[1]) for entry in row)
            for saved_index, value in row:
                physical_index = physical_indices[saved_index]
                dense[vertex_index * len(physical_paths) + physical_index] = float(value) / total

        fn_skin.setWeights(
            _dag_path(shape),
            _vertex_component(vertex_count),
            om.MIntArray(range(len(physical_paths))),
            dense,
            normalize=True,
        )
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


def save_selected():
    """選択メッシュをファイルダイアログ経由で保存する。"""
    selected = cmds.ls(selection=True, long=True) or []
    if len(selected) != 1:
        raise ValueError("保存するメッシュを1つ選択してください。")
    paths = cmds.fileDialog2(fileMode=0, dialogStyle=2, caption="Save Skin Weights", fileFilter="JSON (*.json)")
    if not paths:
        return None
    return save(selected[0], paths[0])


def load_selected():
    """選択メッシュへファイルダイアログ経由で復元する。"""
    selected = cmds.ls(selection=True, long=True) or []
    if len(selected) != 1:
        raise ValueError("復元先メッシュを1つ選択してください。")
    paths = cmds.fileDialog2(fileMode=1, dialogStyle=2, caption="Load Skin Weights", fileFilter="JSON (*.json)")
    if not paths:
        return None
    return load(selected[0], paths[0])
