"""
AutoRemesher Node Tools

autoRemesherNode (Mayaプラグイン、maya/cpp/src/autoRemesherNode.cpp) を使って
選択メッシュのクアッドリメッシュ結果を別オブジェクトとして生成するツール。

autoRemesherNode は inMesh -> outMesh の非破壊ノードだが、トポロジを変更する
ノードをヒストリに直接挿入するのは接続構造が不安定になりやすいため、
このツールでは元のメッシュはそのまま残し、`<元のメッシュ>_remeshed` という
新しいオブジェクトにリメッシュ結果を出力する構成をとる。
"""

import maya.cmds as cmds

PLUGIN_NAME = "ywtatools"


def _ensure_plugin_loaded() -> bool:
    """ywtatools プラグイン（autoRemesherNode を含む）がロードされていることを保証する

    Returns:
        ロードに成功した（またはすでにロードされている）場合True
    """
    if cmds.pluginInfo(PLUGIN_NAME, query=True, loaded=True):
        return True

    try:
        cmds.loadPlugin(PLUGIN_NAME)
    except RuntimeError as e:
        cmds.warning(f"プラグイン '{PLUGIN_NAME}' のロードに失敗しました: {e}")
        return False

    return bool(cmds.pluginInfo(PLUGIN_NAME, query=True, loaded=True))


def create_remesh_node(mesh: str = None) -> str:
    """選択（または指定）されたメッシュに autoRemesherNode を接続し、
    リメッシュ結果を新しいオブジェクトとして生成する

    元のメッシュは変更せずそのまま残す。新しいオブジェクトの名前は
    `<元のメッシュのtransform名>_remeshed` になる。

    Args:
        mesh: 対象メッシュのシェイプまたはトランスフォーム名。
            Noneの場合は現在選択されているオブジェクトを使う。

    Returns:
        作成された autoRemesherNode のノード名。失敗した場合は空文字列。
    """
    if not _ensure_plugin_loaded():
        return ""

    if mesh is None:
        selection = cmds.ls(selection=True)
        if not selection:
            cmds.warning("メッシュが選択されていません。")
            return ""
        mesh = selection[0]

    shapes = cmds.listRelatives(mesh, shapes=True, type="mesh", noIntermediate=True) or []
    if cmds.nodeType(mesh) == "mesh":
        shape = mesh
    elif shapes:
        shape = shapes[0]
    else:
        cmds.warning(f"'{mesh}' はメッシュではありません。")
        return ""

    transform = cmds.listRelatives(shape, parent=True)[0]

    node = cmds.createNode("autoRemesherNode", name=f"{transform}_autoRemesher")
    cmds.connectAttr(f"{shape}.outMesh", f"{node}.inMesh")

    out_transform = cmds.createNode("transform", name=f"{transform}_remeshed")
    out_shape = cmds.createNode(
        "mesh", name=f"{transform}_remeshedShape", parent=out_transform
    )
    cmds.connectAttr(f"{node}.outMesh", f"{out_shape}.inMesh")
    cmds.sets(out_shape, edit=True, forceElement="initialShadingGroup")

    cmds.setAttr(f"{node}.enable", True)

    cmds.select(out_transform, replace=True)

    return node
