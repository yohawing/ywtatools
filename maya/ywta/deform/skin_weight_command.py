"""bulk skin weight write を undoable Maya command へ渡す registry。"""

from __future__ import absolute_import

import math
import os
from pathlib import Path
import uuid

import maya.cmds as cmds

from ywta.core import undo_utils


COMMAND_NAME = "ywtaSetSkinWeights"
PLUGIN_NAME = "ywtaSkinWeightsCmd.py"
_OPERATIONS = {}


def _plugin_path():
    """同梱 Maya plugin の絶対パスを返す。"""
    return str(Path(__file__).resolve().parents[2] / "plug-ins" / PLUGIN_NAME)


def ensure_plugin_loaded():
    """undoable skin weight command plugin を必要時にロードする。"""
    path = _plugin_path()
    if not os.path.isfile(path):
        raise RuntimeError("skin weight command plugin がありません: {}".format(path))
    if not cmds.pluginInfo(path, query=True, loaded=True):
        cmds.loadPlugin(path, quiet=True)
    if not hasattr(cmds, COMMAND_NAME):
        raise RuntimeError("{} command を登録できませんでした。".format(COMMAND_NAME))
    return path


def register_operation(operation):
    """plugin command が1回取得する bulk operation を登録する。"""
    token = uuid.uuid4().hex
    _OPERATIONS[token] = operation
    return token


def take_operation(token):
    """token に対応する operation を registry から取り出す。"""
    try:
        return _OPERATIONS.pop(token)
    except KeyError as error:
        raise RuntimeError("skin weight operation が見つかりません: {}".format(token)) from error


def execute(cluster, shape, component_indices, influence_indices, weights, normalize=True):
    """bulk weight write を Maya Undo queue に1 command として積む。"""
    if not isinstance(cluster, str) or not cluster or not isinstance(shape, str) or not shape:
        raise ValueError("skinClusterとmesh shape名を指定してください。")
    cluster_matches = cmds.ls(cluster, long=True, type="skinCluster") or []
    shape_matches = cmds.ls(shape, long=True, type="mesh") or []
    if len(cluster_matches) != 1 or len(shape_matches) != 1:
        raise ValueError("skinClusterとmesh shapeを一意に解決できません。")
    cluster = cluster_matches[0]
    shape = shape_matches[0]
    history = cmds.ls(cmds.listHistory(shape, pruneDagObjects=True) or [], type="skinCluster") or []
    if cluster not in history:
        raise ValueError("mesh shapeは指定skinClusterの出力ではありません。")
    try:
        components = list(component_indices)
        influences = list(influence_indices)
        values = list(weights)
    except TypeError as error:
        raise ValueError("indexとweightは反復可能な列にしてください。") from error
    for label, indices in (("component", components), ("influence", influences)):
        if not indices:
            raise ValueError("{} indexが空です。".format(label))
        if any(not isinstance(index, int) or isinstance(index, bool) or index < 0 for index in indices):
            raise ValueError("{} indexが不正です。".format(label))
        if len(set(indices)) != len(indices):
            raise ValueError("{} indexが重複しています。".format(label))
    vertex_count = cmds.polyEvaluate(shape, vertex=True)
    influence_count = len(cmds.skinCluster(cluster, query=True, influence=True) or [])
    if any(index >= vertex_count for index in components):
        raise ValueError("component indexが頂点範囲外です。")
    if any(index >= influence_count for index in influences):
        raise ValueError("influence indexが範囲外です。")
    expected = len(components) * len(influences)
    if len(values) != expected:
        raise ValueError("weight件数が不正です: expected={} actual={}".format(expected, len(values)))
    if any(
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or value < 0.0
        for value in values
    ):
        raise ValueError("weightに不正な値があります。")
    if not isinstance(normalize, bool):
        raise ValueError("normalizeはboolにしてください。")
    undo_utils.require_enabled("Set Skin Weights")
    ensure_plugin_loaded()
    operation = {
        "cluster": cluster,
        "shape": shape,
        "component_indices": components,
        "influence_indices": influences,
        "weights": values,
        "normalize": normalize,
    }
    token = register_operation(operation)
    try:
        getattr(cmds, COMMAND_NAME)(token)
    finally:
        _OPERATIONS.pop(token, None)
