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
    components = list(component_indices)
    influences = list(influence_indices)
    values = list(weights)
    for label, indices in (("component", components), ("influence", influences)):
        if not indices:
            raise ValueError("{} indexが空です。".format(label))
        if any(not isinstance(index, int) or isinstance(index, bool) or index < 0 for index in indices):
            raise ValueError("{} indexが不正です。".format(label))
        if len(set(indices)) != len(indices):
            raise ValueError("{} indexが重複しています。".format(label))
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
