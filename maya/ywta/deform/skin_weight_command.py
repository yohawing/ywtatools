"""bulk skin weight write を undoable Maya command へ渡す registry。"""

from __future__ import absolute_import

import os
from pathlib import Path
import uuid

import maya.cmds as cmds


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
    ensure_plugin_loaded()
    operation = {
        "cluster": cluster,
        "shape": shape,
        "component_indices": list(component_indices),
        "influence_indices": list(influence_indices),
        "weights": list(weights),
        "normalize": bool(normalize),
    }
    token = register_operation(operation)
    try:
        getattr(cmds, COMMAND_NAME)(token)
    finally:
        _OPERATIONS.pop(token, None)
