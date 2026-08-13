"""scene を改名せず、設定と選択を復元する原子的 FBX export。"""

from __future__ import absolute_import

from contextlib import contextmanager
import math
import os
import tempfile

import maya.cmds as cmds
import maya.mel as mel


def _ensure_fbx_plugin():
    """Autodesk FBX plugin をロードする。"""
    if not cmds.pluginInfo("fbxmaya", query=True, loaded=True):
        cmds.loadPlugin("fbxmaya", quiet=True)
    if not cmds.pluginInfo("fbxmaya", query=True, loaded=True):
        raise RuntimeError("fbxmaya plugin をロードできません。")


def _export_path(file_path):
    """出力先を絶対 .fbx path へ検証・正規化する。"""
    if not isinstance(file_path, str) or not file_path.strip():
        raise ValueError("FBX 出力先が空です。")
    target = os.path.abspath(file_path)
    if os.path.splitext(target)[1].lower() != ".fbx":
        target += ".fbx"
    directory = os.path.dirname(target)
    if not os.path.isdir(directory):
        raise ValueError("FBX 出力先ディレクトリがありません: {}".format(directory))
    return target


def _nodes(nodes):
    """export node を順序保持したロング名へ解決する。"""
    source = nodes if nodes is not None else cmds.ls(selection=True, long=True)
    if isinstance(source, str):
        source = [source]
    if not source:
        raise ValueError("FBX export 対象を選択してください。")
    result = []
    seen = set()
    for node in source:
        matches = cmds.ls(node, long=True) or []
        if len(matches) != 1:
            raise ValueError("FBX export nodeを一意に解決できません: {}".format(node))
        node_uuid = (cmds.ls(matches[0], uuid=True) or [None])[0]
        if node_uuid is None:
            raise ValueError("FBX export nodeのUUIDを取得できません: {}".format(node))
        if node_uuid not in seen:
            seen.add(node_uuid)
            result.append(matches[0])
    return result


def _mesh_shapes(node):
    """node自身または階層下の表示mesh shapeをロングパスで返す。"""
    matches = cmds.ls(node, long=True) or []
    if len(matches) != 1:
        return []
    node = matches[0]
    if cmds.nodeType(node) == "mesh":
        shapes = [node]
    elif cmds.objectType(node, isAType="transform"):
        shapes = cmds.listRelatives(node, shapes=True, fullPath=True, noIntermediate=True, type="mesh") or []
        shapes.extend(cmds.listRelatives(node, allDescendents=True, fullPath=True, type="mesh") or [])
    else:
        shapes = []
    return list(dict.fromkeys(shape for shape in shapes if not cmds.getAttr(shape + ".intermediateObject")))


def _top_joint(joint):
    """influence jointから最上位のjoint parentへ辿る。"""
    matches = cmds.ls(joint, long=True, type="joint") or []
    if len(matches) != 1:
        raise ValueError("FBX export influence jointを一意に解決できません: {}".format(joint))
    current = matches[0]
    while True:
        parents = cmds.listRelatives(current, parent=True, fullPath=True, type="joint") or []
        if not parents:
            return current
        current = parents[0]


def _include_skin_roots(nodes):
    """skinned meshのexportに必要なtop influence jointを追加する。"""
    result = list(nodes)
    seen = {(cmds.ls(node, uuid=True) or [None])[0] for node in result}
    for node in nodes:
        for shape in _mesh_shapes(node):
            clusters = cmds.ls(cmds.listHistory(shape, pruneDagObjects=True) or [], type="skinCluster") or []
            for cluster in clusters:
                for influence in cmds.skinCluster(cluster, query=True, influence=True) or []:
                    root = _top_joint(influence)
                    node_uuid = (cmds.ls(root, uuid=True) or [None])[0]
                    if node_uuid not in seen:
                        seen.add(node_uuid)
                        result.append(root)
    return result


@contextmanager
def _preserved_fbx_state():
    """FBX settings と Maya selection を成功・失敗に関係なく復元する。"""
    _ensure_fbx_plugin()
    selection = cmds.ls(selection=True, long=True) or []
    mel.eval("FBXPushSettings;")
    try:
        yield
    finally:
        try:
            mel.eval("FBXPopSettings;")
        finally:
            existing = [node for node in selection if cmds.objExists(node)]
            if existing:
                cmds.select(existing, replace=True)
            else:
                cmds.select(clear=True)


def _configure_common():
    """静的・スキン・アニメーション共通の明示 FBX settings を設定する。"""
    mel.eval("FBXExportCameras -v false;")
    mel.eval("FBXExportLights -v false;")
    mel.eval("FBXExportConstraints -v false;")
    mel.eval("FBXExportInAscii -v false;")
    mel.eval("FBXExportInputConnections -v false;")
    mel.eval("FBXExportReferencedAssetsContent -v false;")
    mel.eval("FBXExportShapes -v true;")
    mel.eval("FBXExportSkins -v true;")
    mel.eval("FBXExportSmoothingGroups -v true;")
    mel.eval("FBXExportSmoothMesh -v false;")
    mel.eval("FBXExportTriangulate -v false;")


def _temporary_fbx(target):
    """同一ディレクトリに export 用一時 .fbx path を確保する。"""
    descriptor, path = tempfile.mkstemp(prefix=".ywta_fbx_", suffix=".fbx", dir=os.path.dirname(target))
    os.close(descriptor)
    os.remove(path)
    return path


def _mel_path(path):
    """FBX MEL command に安全に埋め込める path へ変換する。"""
    return path.replace("\\", "/").replace('"', '\\"')


def _export(nodes, target, animation_range=None):
    """検証済み node を temp file へ出し、成功時だけ target と置換する。"""
    temporary = _temporary_fbx(target)
    try:
        with _preserved_fbx_state():
            _configure_common()
            if animation_range is None:
                mel.eval("FBXExportBakeComplexAnimation -v false;")
            else:
                start, end = animation_range
                mel.eval("FBXExportApplyConstantKeyReducer -v true;")
                mel.eval("FBXExportBakeComplexAnimation -v true;")
                mel.eval("FBXExportBakeComplexStart -v {};".format(start))
                mel.eval("FBXExportBakeComplexEnd -v {};".format(end))
                mel.eval("FBXExportBakeComplexStep -v 1;")
            cmds.select(nodes, replace=True)
            mel.eval('FBXExport -f "{}" -s;'.format(_mel_path(temporary)))
        if not os.path.isfile(temporary) or os.path.getsize(temporary) <= 0:
            raise RuntimeError("FBX exporter が有効なファイルを生成しませんでした。")
        os.replace(temporary, target)
    except Exception:
        if os.path.exists(temporary):
            os.remove(temporary)
        raise
    return target


def animation_range():
    """time slider highlightを優先し、なければplayback rangeを返す。"""
    playback = (
        float(cmds.playbackOptions(query=True, minTime=True)),
        float(cmds.playbackOptions(query=True, maxTime=True)),
    )
    try:
        slider = mel.eval("$tmp = $gPlayBackSlider;")
        if not slider or not cmds.timeControl(slider, query=True, rangeVisible=True):
            return playback
        values = cmds.timeControl(slider, query=True, rangeArray=True) or []
        if len(values) != 2:
            return playback
        start, end_exclusive = (float(values[0]), float(values[1]))
        end = end_exclusive - 1.0
        return (start, end) if math.isfinite(start) and math.isfinite(end) and end >= start else playback
    except (RuntimeError, TypeError, ValueError):
        return playback


def export_selected(nodes=None, file_path=None):
    """選択 node を静的/スキン FBX として原子的に export する。"""
    nodes = _include_skin_roots(_nodes(nodes))
    if file_path is None:
        paths = cmds.fileDialog2(
            fileMode=0,
            dialogStyle=2,
            caption="Export Selected FBX",
            fileFilter="FBX (*.fbx)",
        )
        if not paths:
            return None
        file_path = paths[0]
    return _export(nodes, _export_path(file_path))


def export_animation(root=None, file_path=None, start=None, end=None):
    """選択 joint root の animation を bake range 付き FBX へ export する。"""
    if root is None:
        selected = cmds.ls(selection=True, type="joint", long=True) or []
        if len(selected) != 1:
            raise ValueError("animation export の root joint を1つ選択してください。")
        root = selected[0]
    roots = cmds.ls(root, type="joint", long=True) or []
    if len(roots) != 1:
        raise ValueError("root joint を一意に解決できません: {}".format(root))
    joint_parents = cmds.listRelatives(roots[0], parent=True, fullPath=True, type="joint") or []
    if joint_parents:
        raise ValueError("animation export には最上位jointを指定してください: {}".format(roots[0]))
    default_start, default_end = animation_range()
    if start is None:
        start = default_start
    if end is None:
        end = default_end
    if (
        not isinstance(start, (int, float))
        or isinstance(start, bool)
        or not math.isfinite(start)
        or not isinstance(end, (int, float))
        or isinstance(end, bool)
        or not math.isfinite(end)
        or end < start
    ):
        raise ValueError("animation range が不正です: {} - {}".format(start, end))
    if file_path is None:
        paths = cmds.fileDialog2(
            fileMode=0,
            dialogStyle=2,
            caption="Export Animation FBX",
            fileFilter="FBX (*.fbx)",
        )
        if not paths:
            return None
        file_path = paths[0]
    return _export(roots, _export_path(file_path), animation_range=(start, end))
