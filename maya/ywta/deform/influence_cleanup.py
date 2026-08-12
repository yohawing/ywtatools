"""skinCluster 全出力を走査して未使用 influence を安全に削除する。"""

from __future__ import absolute_import

import math

import maya.api.OpenMaya as om
import maya.api.OpenMayaAnim as oma
import maya.cmds as cmds

from ywta.deform import skin_io


DEFAULT_THRESHOLD = 1.0e-8
THRESHOLD_OPTION = "ywtaUnusedInfluenceThreshold"
PROTECT_LOCKED_OPTION = "ywtaUnusedInfluenceProtectLocked"


def _threshold(value):
    """未使用判定 threshold を検証する。"""
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value < 0.0:
        raise ValueError("threshold は0以上の有限値にしてください。")
    return float(value)


def get_settings():
    """optionVarから検証済みcleanup設定を取得する。"""
    threshold = cmds.optionVar(query=THRESHOLD_OPTION) if cmds.optionVar(exists=THRESHOLD_OPTION) else DEFAULT_THRESHOLD
    protect_locked = bool(cmds.optionVar(query=PROTECT_LOCKED_OPTION)) if cmds.optionVar(exists=PROTECT_LOCKED_OPTION) else True
    try:
        threshold = _threshold(threshold)
    except ValueError:
        threshold = DEFAULT_THRESHOLD
    return threshold, protect_locked


def set_settings(threshold, protect_locked):
    """検証済みcleanup設定をoptionVarへ保存する。"""
    threshold = _threshold(threshold)
    if not isinstance(protect_locked, bool):
        raise ValueError("protect_locked は bool にしてください。")
    cmds.optionVar(floatValue=(THRESHOLD_OPTION, threshold))
    cmds.optionVar(intValue=(PROTECT_LOCKED_OPTION, int(protect_locked)))
    return threshold, protect_locked


def _cluster_geometries(cluster):
    """skinCluster の全 mesh output shapes をロングパスで返す。"""
    geometries = cmds.skinCluster(cluster, query=True, geometry=True) or []
    result = []
    for geometry in geometries:
        shapes = cmds.ls(geometry, long=True) or []
        if len(shapes) != 1 or cmds.nodeType(shapes[0]) != "mesh":
            raise ValueError("mesh 以外を含む skinCluster は対象にできません: {}".format(cluster))
        result.append(shapes[0])
    if not result:
        raise ValueError("skinCluster に output geometry がありません: {}".format(cluster))
    return result


def analyze_cluster(cluster, threshold=DEFAULT_THRESHOLD):
    """全 output mesh で最大ウェイトが threshold 以下の influence を返す。"""
    threshold = _threshold(threshold)
    matches = cmds.ls(cluster, type="skinCluster") or []
    if len(matches) != 1:
        raise ValueError("skinCluster を一意に解決できません: {}".format(cluster))
    cluster = matches[0]
    fn_skin = oma.MFnSkinCluster(skin_io._depend_node(cluster))
    influence_paths = [path.fullPathName() for path in fn_skin.influenceObjects()]
    maximums = [0.0] * len(influence_paths)
    for shape in _cluster_geometries(cluster):
        vertex_count = om.MFnMesh(skin_io._dag_path(shape)).numVertices
        weights, influence_count = fn_skin.getWeights(skin_io._dag_path(shape), skin_io._vertex_component(vertex_count))
        if influence_count != len(influence_paths):
            raise RuntimeError("influence count が geometry 間で一致しません: {}".format(cluster))
        for vertex_index in range(vertex_count):
            offset = vertex_index * influence_count
            for influence_index in range(influence_count):
                maximums[influence_index] = max(
                    maximums[influence_index],
                    float(weights[offset + influence_index]),
                )
    return [
        {"influence": influence, "maximum_weight": maximum}
        for influence, maximum in zip(influence_paths, maximums)
        if maximum <= threshold
    ]


def _is_locked(influence):
    """Maya influence lock 属性が有効か判定する。"""
    plug = "{}.lockInfluenceWeights".format(influence)
    return cmds.objExists(plug) and bool(cmds.getAttr(plug))


def _selected_clusters(meshes=None):
    """選択または指定 mesh 群から skinCluster を重複なしで取得する。"""
    source = meshes if meshes is not None else cmds.ls(selection=True, long=True)
    if not source:
        raise ValueError("スキンされた mesh を1つ以上選択してください。")
    clusters = []
    seen = set()
    for mesh in source:
        shape = skin_io._mesh_shape(mesh)
        cluster = skin_io._skin_cluster(shape)
        if cluster is None:
            raise ValueError("skinCluster が見つかりません: {}".format(shape))
        node_uuid = (cmds.ls(cluster, uuid=True) or [None])[0]
        if node_uuid not in seen:
            seen.add(node_uuid)
            clusters.append(cluster)
    return clusters


def find_unused_influences(meshes=None, threshold=DEFAULT_THRESHOLD):
    """対象 skinCluster ごとの未使用 influence を read-only で診断する。"""
    threshold = _threshold(threshold)
    return {cluster: analyze_cluster(cluster, threshold=threshold) for cluster in _selected_clusters(meshes)}


def remove_unused_influences(
    meshes=None,
    threshold=DEFAULT_THRESHOLD,
    protect_locked=True,
):
    """未使用 influence を単一 Undo chunk で削除する。

    全候補は scene 編集前に計算し、locked influence は既定で保護する。
    """
    if not isinstance(protect_locked, bool):
        raise ValueError("protect_locked は bool にしてください。")
    analyses = find_unused_influences(meshes, threshold=threshold)
    plans = []
    protected = []
    for cluster, records in analyses.items():
        current = cmds.skinCluster(cluster, query=True, influence=True) or []
        removable = []
        for record in records:
            influence = record["influence"]
            if protect_locked and _is_locked(influence):
                protected.append(
                    {
                        "cluster": cluster,
                        "influence": influence,
                        "reason": "locked",
                    }
                )
            else:
                removable.append(influence)
        if removable and len(removable) >= len(current):
            raise RuntimeError("全 influence が未使用の skinCluster は変更できません: {}".format(cluster))
        for influence in removable:
            plans.append((cluster, influence))

    if not plans:
        return {"removed": [], "protected": protected}
    cmds.undoInfo(openChunk=True, chunkName="YWTA Remove Unused Influences")
    failed = False
    removed = []
    try:
        for cluster, influence in plans:
            cmds.skinCluster(cluster, edit=True, removeInfluence=influence)
            removed.append({"cluster": cluster, "influence": influence})
    except Exception:
        failed = True
        raise
    finally:
        cmds.undoInfo(closeChunk=True)
        if failed:
            cmds.undo()
    return {"removed": removed, "protected": protected}


def remove_unused_selected(threshold=None, protect_locked=None):
    """現在選択meshの未使用influenceを保存済み設定で削除する。"""
    saved_threshold, saved_protect_locked = get_settings()
    result = remove_unused_influences(
        threshold=saved_threshold if threshold is None else threshold,
        protect_locked=(saved_protect_locked if protect_locked is None else protect_locked),
    )
    if result["removed"]:
        cmds.inViewMessage(
            statusMessage="Removed {} unused skin influence(s).".format(len(result["removed"])),
            position="topCenter",
            fade=True,
        )
    else:
        cmds.warning("未使用 skin influence はありません。")
    return result


def show_options():
    """未使用influence削除のthresholdとlock保護を設定するUIを表示する。"""
    window = "ywtaUnusedInfluenceOptionsWindow"
    if cmds.window(window, exists=True):
        cmds.deleteUI(window)
    threshold, protect_locked = get_settings()
    cmds.window(window, title="YWTA Remove Unused Influences", sizeable=False)
    cmds.columnLayout(adjustableColumn=True, rowSpacing=8, width=390)
    threshold_field = cmds.floatFieldGrp(
        label="Max Weight Threshold",
        numberOfFields=1,
        value1=threshold,
        precision=10,
    )
    protect_field = cmds.checkBox(
        label="Protect locked influences",
        value=protect_locked,
    )

    def apply_options(*_args):
        values = set_settings(
            cmds.floatFieldGrp(threshold_field, query=True, value1=True),
            cmds.checkBox(protect_field, query=True, value=True),
        )
        return remove_unused_selected(*values)

    cmds.button(label="Remove Unused", command=apply_options)
    cmds.showWindow(window)
    return window
