"""隣接頂点平均を使う局所skin weight smoothing。"""

from __future__ import absolute_import

import math
import re

import maya.api.OpenMaya as om
import maya.api.OpenMayaAnim as oma
import maya.cmds as cmds

from ywta.deform import skin_io
from ywta.deform import skin_weight_command
from ywta.core import undo_utils


_VERTEX_RE = re.compile(r"^(.*)\.vtx\[(\d+)\]$")
STRENGTH_OPTION = "ywtaSkinSmoothStrength"
ITERATIONS_OPTION = "ywtaSkinSmoothIterations"
DEFAULT_STRENGTH = 0.5
DEFAULT_ITERATIONS = 1


def _settings(strength, iterations):
    """smoothing設定を検証する。"""
    if (
        not isinstance(strength, (int, float))
        or isinstance(strength, bool)
        or not math.isfinite(strength)
        or not 0.0 <= strength <= 1.0
    ):
        raise ValueError("strengthは0以上1以下の有限値にしてください。")
    if not isinstance(iterations, int) or isinstance(iterations, bool) or iterations < 1:
        raise ValueError("iterationsは1以上の整数にしてください。")
    return float(strength), iterations


def get_settings():
    """optionVarから検証済みsmoothing設定を取得する。"""
    strength = cmds.optionVar(query=STRENGTH_OPTION) if cmds.optionVar(exists=STRENGTH_OPTION) else DEFAULT_STRENGTH
    iterations = cmds.optionVar(query=ITERATIONS_OPTION) if cmds.optionVar(exists=ITERATIONS_OPTION) else DEFAULT_ITERATIONS
    try:
        return _settings(strength, iterations)
    except ValueError:
        return DEFAULT_STRENGTH, DEFAULT_ITERATIONS


def set_settings(strength, iterations):
    """検証済みsmoothing設定をoptionVarへ保存する。"""
    strength, iterations = _settings(strength, iterations)
    cmds.optionVar(floatValue=(STRENGTH_OPTION, strength))
    cmds.optionVar(intValue=(ITERATIONS_OPTION, iterations))
    return strength, iterations


def _selected_groups(components=None):
    """選択componentをmesh shapeごとのvertex indexへ正規化する。"""
    source = components if components is not None else cmds.ls(selection=True, flatten=True)
    converted = cmds.polyListComponentConversion(source or [], toVertex=True) or []
    expanded = cmds.filterExpand(converted, selectionMask=31, expand=True) or []
    if not expanded:
        raise ValueError("smoothingするpolygon componentを1つ以上選択してください。")
    groups = {}
    for component in expanded:
        match = _VERTEX_RE.match(component)
        if not match:
            raise ValueError("vertex componentを解決できません: {}".format(component))
        shape = skin_io._mesh_shape(match.group(1))
        groups.setdefault(shape, set()).add(int(match.group(2)))
    return {shape: sorted(indices) for shape, indices in groups.items()}


def _adjacency(shape, indices):
    """対象頂点ごとの接続頂点indexをAPI 2.0で取得する。"""
    iterator = om.MItMeshVertex(skin_io._dag_path(shape))
    result = {}
    for index in indices:
        iterator.setIndex(index)
        neighbors = list(iterator.getConnectedVertices())
        if not neighbors:
            raise ValueError("接続頂点がないためsmoothingできません: {}.vtx[{}]".format(shape, index))
        result[index] = neighbors
    return result


def _locked_indices(fn_skin):
    """lockInfluenceWeightsが有効なphysical influence index集合を返す。"""
    result = set()
    for index, path in enumerate(fn_skin.influenceObjects()):
        plug = path.fullPathName() + ".lockInfluenceWeights"
        if cmds.objExists(plug) and cmds.getAttr(plug):
            result.add(index)
    return result


def _smoothed_rows(shape, indices, strength, iterations):
    """sceneを変更せず対象頂点のdense smoothing結果を計算する。"""
    cluster = skin_io._skin_cluster(shape)
    if cluster is None:
        raise ValueError("skinClusterが見つかりません: {}".format(shape))
    fn_skin = oma.MFnSkinCluster(skin_io._depend_node(cluster))
    vertex_count = om.MFnMesh(skin_io._dag_path(shape)).numVertices
    weights, influence_count = fn_skin.getWeights(skin_io._dag_path(shape), skin_io._vertex_component(vertex_count))
    current = [
        [float(weights[row * influence_count + column]) for column in range(influence_count)] for row in range(vertex_count)
    ]
    adjacency = _adjacency(shape, indices)
    locked = _locked_indices(fn_skin)
    unlocked = [index for index in range(influence_count) if index not in locked]
    for _iteration in range(iterations):
        updated = [row[:] for row in current]
        for vertex_index in indices:
            neighbors = adjacency[vertex_index]
            row = current[vertex_index][:]
            for influence_index in unlocked:
                average = sum(current[neighbor][influence_index] for neighbor in neighbors) / len(neighbors)
                row[influence_index] = current[vertex_index][influence_index] * (1.0 - strength) + average * strength
            remaining = max(0.0, 1.0 - sum(row[index] for index in locked))
            unlocked_total = sum(row[index] for index in unlocked)
            if unlocked and unlocked_total <= skin_io.WEIGHT_EPSILON and remaining > 0.0:
                for influence_index in unlocked:
                    row[influence_index] = current[vertex_index][influence_index]
                unlocked_total = sum(row[index] for index in unlocked)
            if unlocked and unlocked_total > skin_io.WEIGHT_EPSILON:
                scale = remaining / unlocked_total
                for influence_index in unlocked:
                    row[influence_index] *= scale
            updated[vertex_index] = row
        current = updated
    dense = [value for vertex_index in indices for value in current[vertex_index]]
    return {
        "shape": shape,
        "cluster": cluster,
        "indices": indices,
        "influence_count": influence_count,
        "weights": dense,
    }


def smooth(components=None, strength=0.5, iterations=1):
    """選択頂点をJacobi型隣接平均で単一Undo smoothingする。"""
    strength, iterations = _settings(strength, iterations)
    plans = [_smoothed_rows(shape, indices, strength, iterations) for shape, indices in _selected_groups(components).items()]
    undo_utils.require_enabled("Smooth Skin Weights")
    cmds.undoInfo(openChunk=True, chunkName="YWTA Smooth Skin Weights")
    failed = False
    try:
        for plan in plans:
            skin_weight_command.execute(
                plan["cluster"],
                plan["shape"],
                plan["indices"],
                range(plan["influence_count"]),
                plan["weights"],
                normalize=False,
            )
    except Exception:
        failed = True
        raise
    finally:
        cmds.undoInfo(closeChunk=True)
        if failed:
            cmds.undo()
    return {
        "meshes": len(plans),
        "vertices": sum(len(plan["indices"]) for plan in plans),
        "strength": strength,
        "iterations": iterations,
    }


def smooth_selected(strength=None, iterations=None):
    """現在選択を保存済み設定でsmoothingする。"""
    saved_strength, saved_iterations = get_settings()
    return smooth(
        strength=saved_strength if strength is None else strength,
        iterations=saved_iterations if iterations is None else iterations,
    )


def show_options():
    """Skin Smooth設定と実行ボタンを持つMayaネイティブUIを表示する。"""
    window = "ywtaSkinSmoothOptionsWindow"
    if cmds.window(window, exists=True):
        cmds.deleteUI(window)
    strength, iterations = get_settings()
    cmds.window(window, title="YWTA Skin Smooth", sizeable=False)
    cmds.columnLayout(adjustableColumn=True, rowSpacing=8, width=360)
    strength_field = cmds.floatSliderGrp(
        label="Strength",
        field=True,
        minValue=0.0,
        maxValue=1.0,
        fieldMinValue=0.0,
        fieldMaxValue=1.0,
        value=strength,
    )
    iterations_field = cmds.intSliderGrp(
        label="Iterations",
        field=True,
        minValue=1,
        maxValue=20,
        fieldMinValue=1,
        fieldMaxValue=100,
        value=iterations,
    )

    def apply_options(*_args):
        values = set_settings(
            cmds.floatSliderGrp(strength_field, query=True, value=True),
            cmds.intSliderGrp(iterations_field, query=True, value=True),
        )
        return smooth_selected(*values)

    cmds.button(label="Apply Smooth", command=apply_options)
    cmds.showWindow(window)
    return window
