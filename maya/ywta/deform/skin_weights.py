"""選択頂点向けの安全なスキンウェイト clipboard / average ツール。"""

from __future__ import absolute_import

import math
import re

import maya.api.OpenMaya as om
import maya.api.OpenMayaAnim as oma
import maya.cmds as cmds

from ywta.deform import skin_io


_VERTEX_RE = re.compile(r"^(.*)\.vtx\[(\d+)\]$")
_CLIPBOARD = None


def _selected_vertex_indices(vertices=None):
    """単一 mesh 上の頂点選択を shape と index 列へ正規化する。"""
    source = vertices if vertices is not None else cmds.ls(selection=True, flatten=True)
    converted = cmds.polyListComponentConversion(source or [], toVertex=True) or []
    expanded = cmds.filterExpand(converted, selectionMask=31, expand=True) or []
    if not expanded:
        raise ValueError("polygon vertex を1つ以上選択してください。")
    shape = None
    indices = []
    seen = set()
    for component in expanded:
        match = _VERTEX_RE.match(component)
        if not match:
            raise ValueError("vertex component を解決できません: {}".format(component))
        component_shape = skin_io._mesh_shape(match.group(1))
        if shape is None:
            shape = component_shape
        elif component_shape != shape:
            raise ValueError("頂点選択は1つの mesh に限定してください。")
        index = int(match.group(2))
        if index not in seen:
            seen.add(index)
            indices.append(index)
    return shape, indices


def _component(indices):
    """頂点 index 列から Maya component object を作る。"""
    component = om.MFnSingleIndexedComponent().create(om.MFn.kMeshVertComponent)
    om.MFnSingleIndexedComponent(component).addElements(indices)
    return component


def _influence_records(fn_skin):
    """skinCluster influences を可搬名付き辞書へ変換する。"""
    records = []
    for path in fn_skin.influenceObjects():
        full_path = path.fullPathName()
        records.append({"name": full_path.rsplit("|", 1)[-1], "path": full_path})
    return records


def capture_vertex_weights(vertex=None):
    """1頂点の influence weights を clipboard 形式で取得する。"""
    shape, indices = _selected_vertex_indices([vertex] if vertex else None)
    if len(indices) != 1:
        raise ValueError("コピー元 vertex を1つだけ選択してください。")
    cluster = skin_io._skin_cluster(shape)
    if cluster is None:
        raise ValueError("skinCluster が見つかりません: {}".format(shape))
    fn_skin = oma.MFnSkinCluster(skin_io._depend_node(cluster))
    weights, influence_count = fn_skin.getWeights(skin_io._dag_path(shape), _component(indices))
    values = [float(weights[index]) for index in range(influence_count)]
    return {"influences": _influence_records(fn_skin), "weights": values}


def _validate_weights(data):
    """clipboard data を scene 編集前に検証する。"""
    if not isinstance(data, dict):
        raise ValueError("スキンウェイト clipboard が不正です。")
    influences = data.get("influences")
    weights = data.get("weights")
    if not isinstance(influences, list) or not influences or not isinstance(weights, list) or len(weights) != len(influences):
        raise ValueError("influence と weight の件数が一致しません。")
    total = 0.0
    keys = set()
    for influence, weight in zip(influences, weights):
        if (
            not isinstance(influence, dict)
            or not isinstance(influence.get("name"), str)
            or not isinstance(influence.get("path"), str)
        ):
            raise ValueError("influence が不正です。")
        key = (influence["path"], influence["name"])
        if key in keys:
            raise ValueError("influence が重複しています: {}".format(influence["name"]))
        keys.add(key)
        if not isinstance(weight, (int, float)) or isinstance(weight, bool) or not math.isfinite(weight) or weight < 0.0:
            raise ValueError("weight が不正です。")
        total += float(weight)
    if total <= skin_io.WEIGHT_EPSILON:
        raise ValueError("weight 合計が0です。")
    return data


def copy_selected_vertex_weights():
    """選択した1頂点のウェイトを process 内 clipboard へ保存する。"""
    global _CLIPBOARD
    _CLIPBOARD = capture_vertex_weights()
    return _CLIPBOARD


def _set_uniform_weights(shape, indices, data, chunk_name):
    """検証済み1頂点ウェイトを複数頂点へ一括設定する。"""
    data = _validate_weights(data)
    influences = skin_io._resolve_influences(data["influences"])
    cmds.undoInfo(openChunk=True, chunkName=chunk_name)
    failed = False
    try:
        cluster = skin_io._ensure_skin_cluster(shape, influences)
        total = sum(float(value) for value in data["weights"])
        transform_values = [(influence, float(value) / total) for influence, value in zip(influences, data["weights"])]
        components = ["{}.vtx[{}]".format(shape, index) for index in indices]
        cmds.skinPercent(
            cluster,
            components,
            transformValue=transform_values,
            normalize=True,
            zeroRemainingInfluences=True,
        )
    except Exception:
        failed = True
        raise
    finally:
        cmds.undoInfo(closeChunk=True)
        if failed:
            cmds.undo()
    return cluster


def paste_vertex_weights(vertices=None, data=None):
    """clipboard ウェイトを選択頂点群へ貼り付ける。"""
    data = _CLIPBOARD if data is None else data
    if data is None:
        raise ValueError("先にコピー元 vertex のウェイトをコピーしてください。")
    shape, indices = _selected_vertex_indices(vertices)
    return _set_uniform_weights(shape, indices, data, "YWTA Paste Vertex Weights")


def average_vertex_weights(vertices=None):
    """選択頂点群のウェイトを平均し、全選択頂点へ適用する。"""
    shape, indices = _selected_vertex_indices(vertices)
    if len(indices) < 2:
        raise ValueError("平均化する vertex を2つ以上選択してください。")
    cluster = skin_io._skin_cluster(shape)
    if cluster is None:
        raise ValueError("skinCluster が見つかりません: {}".format(shape))
    fn_skin = oma.MFnSkinCluster(skin_io._depend_node(cluster))
    weights, influence_count = fn_skin.getWeights(skin_io._dag_path(shape), _component(indices))
    averages = []
    for influence_index in range(influence_count):
        total = sum(float(weights[row * influence_count + influence_index]) for row in range(len(indices)))
        averages.append(total / len(indices))
    data = {"influences": _influence_records(fn_skin), "weights": averages}
    return _set_uniform_weights(shape, indices, data, "YWTA Average Vertex Weights")
