"""選択頂点向けの安全なスキンウェイト clipboard / average ツール。"""

from __future__ import absolute_import

import json
import math
import os
import re
import tempfile

import maya.api.OpenMaya as om
import maya.api.OpenMayaAnim as oma
import maya.cmds as cmds

from ywta.deform import skin_io
from ywta.core import undo_utils


_VERTEX_RE = re.compile(r"^(.*)\.vtx\[(\d+)\]$")
_CLIPBOARD = None
CLIPBOARD_FORMAT = "ywta.vertex_weight_clipboard"
CLIPBOARD_VERSION = 1
CLIPBOARD_FILENAME = "ywta_vertex_weight_clipboard.json"


def _selected_vertex_groups(vertices=None):
    """頂点選択をmesh shapeごとのindex列へ正規化する。"""
    source = vertices if vertices is not None else cmds.ls(selection=True, flatten=True)
    converted = cmds.polyListComponentConversion(source or [], toVertex=True) or []
    expanded = cmds.filterExpand(converted, selectionMask=31, expand=True) or []
    if not expanded:
        raise ValueError("polygon vertex を1つ以上選択してください。")
    groups = {}
    for component in expanded:
        match = _VERTEX_RE.match(component)
        if not match:
            raise ValueError("vertex component を解決できません: {}".format(component))
        shape = skin_io._mesh_shape(match.group(1))
        index = int(match.group(2))
        group = groups.setdefault(shape, {"indices": [], "seen": set()})
        if index not in group["seen"]:
            group["seen"].add(index)
            group["indices"].append(index)
    return [(shape, group["indices"]) for shape, group in groups.items()]


def _selected_vertex_indices(vertices=None):
    """単一mesh上の頂点選択をshapeとindex列へ正規化する。"""
    groups = _selected_vertex_groups(vertices)
    if len(groups) != 1:
        raise ValueError("頂点選択は1つの mesh に限定してください。")
    return groups[0]


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
            or not influence["name"]
            or influence["name"] != influence["name"].strip()
            or not influence["path"]
            or influence["path"] != influence["path"].strip()
        ):
            raise ValueError("influence が不正です。")
        key = (influence["path"], influence["name"])
        if key in keys:
            raise ValueError("influence が重複しています: {}".format(influence["name"]))
        keys.add(key)
        if (
            not isinstance(weight, (int, float))
            or isinstance(weight, bool)
            or not math.isfinite(weight)
            or weight < 0.0
            or weight > 1.0
        ):
            raise ValueError("weight が不正です。")
        total += float(weight)
    if total <= skin_io.WEIGHT_EPSILON:
        raise ValueError("weight 合計が0です。")
    return data


def clipboard_path():
    """Mayaユーザー間で永続化するclipboard JSONパスを返す。"""
    return os.path.join(cmds.internalVar(userAppDir=True), CLIPBOARD_FILENAME)


def write_clipboard(data, file_path=None):
    """検証済みclipboardをversion付きJSONへ原子的に保存する。"""
    data = _validate_weights(data)
    target = os.path.abspath(file_path or clipboard_path())
    directory = os.path.dirname(target)
    if not os.path.isdir(directory):
        raise ValueError("clipboard保存先ディレクトリがありません: {}".format(directory))
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=directory,
        prefix=".ywta_weight_clipboard_",
        suffix=".tmp",
        delete=False,
    )
    temporary = handle.name
    try:
        with handle:
            json.dump(
                {
                    "format": CLIPBOARD_FORMAT,
                    "version": CLIPBOARD_VERSION,
                    "data": data,
                },
                handle,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            handle.write("\n")
        os.replace(temporary, target)
    except Exception:
        if os.path.exists(temporary):
            os.remove(temporary)
        raise
    return target


def read_clipboard(file_path=None):
    """version付きclipboard JSONを読み込み、完全検証する。"""
    source = os.path.abspath(file_path or clipboard_path())
    if not os.path.isfile(source):
        raise ValueError("先にコピー元vertexのウェイトをコピーしてください。")
    try:
        with open(source, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError) as error:
        raise ValueError("スキンウェイトclipboard JSONを読み込めません。") from error
    if not isinstance(payload, dict) or payload.get("format") != CLIPBOARD_FORMAT:
        raise ValueError("YWTAスキンウェイトclipboardではありません。")
    if payload.get("version") != CLIPBOARD_VERSION:
        raise ValueError("未対応のclipboard versionです: {}".format(payload.get("version")))
    return _validate_weights(payload.get("data"))


def copy_selected_vertex_weights(file_path=None):
    """選択した1頂点のウェイトを永続clipboardへ保存する。"""
    global _CLIPBOARD
    data = capture_vertex_weights()
    write_clipboard(data, file_path=file_path)
    _CLIPBOARD = data
    return _CLIPBOARD


def capture_average_vertex_weights(vertices=None):
    """選択した複数頂点の平均ウェイトをclipboard形式で取得する。"""
    shape, indices = _selected_vertex_indices(vertices)
    if len(indices) < 2:
        raise ValueError("平均をコピーするvertexを2つ以上選択してください。")
    cluster = skin_io._skin_cluster(shape)
    if cluster is None:
        raise ValueError("skinCluster が見つかりません: {}".format(shape))
    fn_skin = oma.MFnSkinCluster(skin_io._depend_node(cluster))
    weights, influence_count = fn_skin.getWeights(skin_io._dag_path(shape), _component(indices))
    averages = []
    for influence_index in range(influence_count):
        total = sum(float(weights[row * influence_count + influence_index]) for row in range(len(indices)))
        averages.append(total / len(indices))
    return {"influences": _influence_records(fn_skin), "weights": averages}


def copy_average_vertex_weights(vertices=None, file_path=None):
    """選択頂点の平均ウェイトを永続clipboardへ保存する。"""
    global _CLIPBOARD
    data = capture_average_vertex_weights(vertices)
    write_clipboard(data, file_path=file_path)
    _CLIPBOARD = data
    return _CLIPBOARD


def _set_uniform_weight_groups(groups, data, chunk_name):
    """検証済みclipboardウェイトを複数meshへ単一Undoで設定する。"""
    data = _validate_weights(data)
    influences = skin_io._resolve_influences(data["influences"])
    skin_io._require_unlocked_nodes(influences)
    original_selection = cmds.ls(selection=True, long=True, flatten=True) or []
    undo_utils.require_enabled(chunk_name)
    cmds.undoInfo(openChunk=True, chunkName=chunk_name)
    failed = False
    clusters = []
    try:
        total = sum(float(value) for value in data["weights"])
        transform_values = [(influence, float(value) / total) for influence, value in zip(influences, data["weights"])]
        for shape, indices in groups:
            cluster = skin_io._ensure_skin_cluster(shape, influences)
            locked = [
                influence
                for influence in (cmds.skinCluster(cluster, query=True, influence=True) or [])
                if cmds.objExists(influence + ".lockInfluenceWeights") and cmds.getAttr(influence + ".lockInfluenceWeights")
            ]
            if locked:
                raise ValueError("locked influenceがあるためウェイトを変更できません: {}".format(", ".join(locked)))
            components = ["{}.vtx[{}]".format(shape, index) for index in indices]
            cmds.skinPercent(
                cluster,
                components,
                transformValue=transform_values,
                normalize=True,
                zeroRemainingInfluences=True,
            )
            clusters.append(cluster)
    except Exception:
        failed = True
        raise
    finally:
        try:
            skin_io._restore_selection(original_selection)
        except Exception:
            failed = True
            raise
        finally:
            cmds.undoInfo(closeChunk=True)
            if failed:
                cmds.undo()
    return clusters


def _set_uniform_weights(shape, indices, data, chunk_name):
    """単一mesh互換入口から検証済みclipboardウェイトを設定する。"""
    return _set_uniform_weight_groups([(shape, indices)], data, chunk_name)[0]


def paste_vertex_weights(vertices=None, data=None, clipboard_file=None):
    """clipboard ウェイトを選択頂点群へ貼り付ける。"""
    if data is None:
        source = os.path.abspath(clipboard_file or clipboard_path())
        if clipboard_file is not None:
            data = read_clipboard(source)
        else:
            data = read_clipboard(source) if os.path.isfile(source) else _CLIPBOARD
        if data is None:
            raise ValueError("先にコピー元vertexのウェイトをコピーしてください。")
    groups = _selected_vertex_groups(vertices)
    clusters = _set_uniform_weight_groups(groups, data, "YWTA Paste Vertex Weights")
    return clusters[0] if len(clusters) == 1 else clusters


def average_vertex_weights(vertices=None):
    """選択頂点群のウェイトを平均し、全選択頂点へ適用する。"""
    shape, indices = _selected_vertex_indices(vertices)
    if len(indices) < 2:
        raise ValueError("平均化する vertex を2つ以上選択してください。")
    data = capture_average_vertex_weights(vertices)
    return _set_uniform_weights(shape, indices, data, "YWTA Average Vertex Weights")
