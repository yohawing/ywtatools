"""
AutoRemesher Node Tools

autoRemesherNode (Mayaプラグイン、maya/cpp/src/autoRemesherNode.cpp) を使って
選択メッシュのクアッドリメッシュ結果を別オブジェクトとして生成するツール。

autoRemesherNode は inMesh -> outMesh の非破壊ノードだが、トポロジを変更する
ノードをヒストリに直接挿入するのは接続構造が不安定になりやすいため、
このツールでは元のメッシュはそのまま残し、`<元のメッシュ>_remeshed` という
新しいオブジェクトにリメッシュ結果を出力する構成をとる。

`show_options()` でパラメータ入力用のオプションウィンドウを表示してから
ノードを作成できる（メニューからはこちらを呼ぶ）。
"""

import maya.cmds as cmds

PLUGIN_NAME = "ywtatools"

# モデルタイプの選択肢（autoRemesherNode.modelType に対応。0=Organic, 1=HardSurface）
MODEL_TYPE_ITEMS = ("Organic", "Hard Surface")

_OPTIONS_WINDOW_NAME = "ywta_autoRemesherOptionsWindow"


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


def create_remesh_node(
    mesh: str = None,
    target_count: int = None,
    adaptivity: float = None,
    edge_scaling: float = None,
    model_type: int = None,
) -> str:
    """選択（または指定）されたメッシュに autoRemesherNode を接続し、
    リメッシュ結果を新しいオブジェクトとして生成する

    元のメッシュは変更せずそのまま残す。新しいオブジェクトの名前は
    `<元のメッシュのtransform名>_remeshed` になる。

    Args:
        mesh: 対象メッシュのシェイプまたはトランスフォーム名。
            Noneの場合は現在選択されているオブジェクトを使う。
        target_count: 目標三角形数（autoRemesherNode.targetCount）。
            Noneの場合はノードのデフォルト値を使う。
        adaptivity: 適応度（0.0〜1.0、autoRemesherNode.adaptivity）。
            Noneの場合はノードのデフォルト値を使う。
        edge_scaling: エッジスケール（autoRemesherNode.edgeScaling）。
            Noneの場合はノードのデフォルト値を使う。
        model_type: モデルタイプ（0=Organic, 1=HardSurface、autoRemesherNode.modelType）。
            Noneの場合はノードのデフォルト値を使う。

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

    if target_count is not None:
        cmds.setAttr(f"{node}.targetCount", target_count)
    if adaptivity is not None:
        cmds.setAttr(f"{node}.adaptivity", adaptivity)
    if edge_scaling is not None:
        cmds.setAttr(f"{node}.edgeScaling", edge_scaling)
    if model_type is not None:
        cmds.setAttr(f"{node}.modelType", model_type)

    cmds.setAttr(f"{node}.enable", True)

    # ノードを選択状態にしてAttribute Editorに表示させる
    cmds.select(node, replace=True)

    return node


def show_options():
    """AutoRemesherのパラメータを指定するオプションウィンドウを表示する

    ウィンドウの「Create Node」ボタンから `create_remesh_node()` を実行する。

    Returns:
        作成されたウィンドウ名
    """
    if cmds.window(_OPTIONS_WINDOW_NAME, exists=True):
        cmds.deleteUI(_OPTIONS_WINDOW_NAME, window=True)

    window = cmds.window(
        _OPTIONS_WINDOW_NAME,
        title="AutoRemesher Options",
        widthHeight=(320, 200),
        sizeable=False,
    )

    cmds.columnLayout(adjustableColumn=True, rowSpacing=6, columnAttach=("both", 8))

    target_count_field = cmds.intFieldGrp(
        numberOfFields=1,
        label="Target Count",
        value1=8000,
        annotation="リメッシュ後の目標三角形数",
    )
    adaptivity_field = cmds.floatSliderGrp(
        label="Adaptivity",
        field=True,
        minValue=0.0,
        maxValue=1.0,
        value=1.0,
        annotation="細部の形状変化への追従度（0.0〜1.0）",
    )
    edge_scaling_field = cmds.floatFieldGrp(
        numberOfFields=1,
        label="Edge Scaling",
        value1=1.0,
        annotation="生成されるクアッドのエッジ長スケーリング",
    )
    model_type_field = cmds.optionMenuGrp(label="Model Type", annotation="リメッシュ対象の形状の種類")
    for item in MODEL_TYPE_ITEMS:
        cmds.menuItem(label=item)

    cmds.separator(height=10, style="in")

    def _on_create(*_args):
        target_count = cmds.intFieldGrp(target_count_field, query=True, value1=True)
        adaptivity = cmds.floatSliderGrp(adaptivity_field, query=True, value=True)
        edge_scaling = cmds.floatFieldGrp(edge_scaling_field, query=True, value1=True)
        model_type = cmds.optionMenuGrp(model_type_field, query=True, select=True) - 1

        node = create_remesh_node(
            target_count=target_count,
            adaptivity=adaptivity,
            edge_scaling=edge_scaling,
            model_type=model_type,
        )
        if node and cmds.window(_OPTIONS_WINDOW_NAME, exists=True):
            cmds.deleteUI(_OPTIONS_WINDOW_NAME, window=True)

    cmds.button(label="Create Node", command=_on_create, height=30)

    cmds.showWindow(window)
    return window
