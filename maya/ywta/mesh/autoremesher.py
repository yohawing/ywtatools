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

`finalize_remesh()` は接続済みノードの現在結果を target へ確定し、必要に
応じて source の UV と skin weight を転送する。source 側のヒストリは保持する。
"""

from pathlib import Path

import maya.cmds as cmds

from ywta.core import undo_utils
from ywta.deform import skin_io

PLUGIN_NAME = "ywtatools"

# モデルタイプの選択肢（autoRemesherNode.modelType に対応。0=Organic, 1=HardSurface）
MODEL_TYPE_ITEMS = ("Organic", "Hard Surface")

_OPTIONS_WINDOW_NAME = "ywta_autoRemesherOptionsWindow"
_FINALIZE_CHUNK_NAME = "YWTA AutoRemesher Finalize"


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
        version = str(cmds.about(version=True)).split(".", 1)[0]
        plugin_path = Path(__file__).resolve().parents[2] / "plug-ins" / version / "ywtatools.mll"
        if not plugin_path.is_file():
            cmds.warning(f"プラグイン '{PLUGIN_NAME}' のロードに失敗しました: {e}")
            return False
        try:
            cmds.loadPlugin(str(plugin_path))
        except RuntimeError as path_error:
            cmds.warning(f"プラグイン '{PLUGIN_NAME}' のロードに失敗しました: {path_error}")
            return False

    return bool(cmds.pluginInfo(PLUGIN_NAME, query=True, loaded=True))


def create_remesh_node(
    mesh: str = None,
    target_count: int = None,
    adaptivity: float = None,
    edge_scaling: float = None,
    model_type: int = None,
    sharp_edge_degrees: float = None,
    smooth_normal_degrees: float = None,
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
        sharp_edge_degrees: シャープエッジと判定する角度（度、autoRemesherNode.sharpEdgeDegrees）。
            Noneの場合はノードのデフォルト値（90.0）を使う。
        smooth_normal_degrees: 法線を平滑化する角度（度、autoRemesherNode.smoothNormalDegrees）。
            Noneの場合はノードのデフォルト値（0.0）を使う。

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
    source_world_matrix = cmds.xform(transform, query=True, matrix=True, worldSpace=True)

    node = cmds.createNode("autoRemesherNode", name=f"{transform}_autoRemesher")
    cmds.connectAttr(f"{shape}.outMesh", f"{node}.inMesh")

    out_transform = cmds.createNode("transform", name=f"{transform}_remeshed")
    # outMesh は入力シェイプのオブジェクト空間なので、元のワールド行列を
    # 出力トランスフォームへコピーして表示位置を一致させる。
    cmds.xform(out_transform, matrix=source_world_matrix, worldSpace=True)
    out_shape = cmds.createNode("mesh", name=f"{transform}_remeshedShape", parent=out_transform)
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
    if sharp_edge_degrees is not None:
        cmds.setAttr(f"{node}.sharpEdgeDegrees", sharp_edge_degrees)
    if smooth_normal_degrees is not None:
        cmds.setAttr(f"{node}.smoothNormalDegrees", smooth_normal_degrees)

    cmds.setAttr(f"{node}.enable", True)

    # ノードを選択状態にしてAttribute Editorに表示させる
    cmds.select(node, replace=True)

    return node


def _resolve_finalize_node(node=None):
    """指定または選択された項目から autoRemesherNode を一意に解決する。"""
    candidates = cmds.ls(node, long=True) if node is not None else cmds.ls(selection=True, long=True)
    candidates = candidates or []
    if len(candidates) != 1:
        raise ValueError("Finalize対象のautoRemesherNodeを1つだけ指定または選択してください。")

    candidate = candidates[0]
    if cmds.nodeType(candidate) == "autoRemesherNode":
        return candidate

    history = cmds.listHistory(candidate, pruneDagObjects=True) or []
    remesh_nodes = [item for item in dict.fromkeys(history) if cmds.nodeType(item) == "autoRemesherNode"]
    if len(remesh_nodes) != 1:
        raise ValueError("対象からautoRemesherNodeを一意に解決できません: {}".format(candidate))
    return remesh_nodes[0]


def _resolve_mesh_connection(node, attribute, source, destination):
    """ノードの mesh 接続を一意に解決し、接続元/先の shape 名を返す。"""
    plugs = (
        cmds.listConnections(
            "{}.{}".format(node, attribute),
            source=source,
            destination=destination,
            plugs=True,
        )
        or []
    )
    shapes = []
    for plug in plugs:
        shape = plug.split(".", 1)[0]
        if cmds.nodeType(shape) != "mesh":
            continue
        if shape not in shapes:
            shapes.append(shape)
    if len(shapes) != 1:
        raise ValueError("{} のmesh接続を一意に解決できません: {}".format(attribute, node))
    if cmds.getAttr(shape + ".intermediateObject"):
        raise ValueError("intermediate shape はFinalize対象にできません: {}".format(shape))
    return cmds.ls(shapes[0], long=True)[0]


def _resolve_finalize_meshes(node):
    """autoRemesherNode から source shape と target transform を取得する。"""
    source_shape = _resolve_mesh_connection(node, "inMesh", source=True, destination=False)
    target_shape = _resolve_mesh_connection(node, "outMesh", source=False, destination=True)
    source_parent = cmds.listRelatives(source_shape, parent=True, fullPath=True) or []
    target_parent = cmds.listRelatives(target_shape, parent=True, fullPath=True) or []
    if len(source_parent) != 1 or len(target_parent) != 1:
        raise ValueError("Finalize対象のmesh transformを一意に解決できません。")
    if cmds.ls(source_shape, uuid=True) == cmds.ls(target_shape, uuid=True):
        raise ValueError("source と target に同じmeshを指定できません。")
    return source_shape, target_shape, target_parent[0]


def _capture_finalize_skin(source_shape, target_shape):
    """source skin の転送前検証を行い、skin data またはNoneを返す。"""
    source_cluster = skin_io._skin_cluster(source_shape)
    if not source_cluster:
        return None

    data = skin_io.capture(source_shape)
    influences = skin_io._resolve_influences(data["influences"])
    skin_io._require_unlocked_nodes(influences)
    target_cluster = skin_io._skin_cluster(target_shape)
    if target_cluster:
        raise ValueError("Finalize対象targetに既存skinClusterがあります: {}".format(target_cluster))
    return data


def _transfer_finalize_uvs(source_shape, target_shape):
    """source の全UV setをclosest pointでtargetへ転送する。"""
    source_uv_sets = cmds.polyUVSet(source_shape, query=True, allUVSets=True) or []
    if not source_uv_sets:
        return False
    cmds.transferAttributes(
        source_shape,
        target_shape,
        transferUVs=2,
        transferNormals=0,
        transferColors=0,
        sampleSpace=0,
        searchMethod=3,
        flipUVs=False,
        colorBorders=False,
    )
    return True


def finalize_remesh(node=None, transfer_uvs=True, transfer_skin=True):
    """AutoRemesherの現在結果をtargetへ確定する。

    source のヒストリは変更せず、target の AutoRemesher/UV転送ヒストリだけを
    bakeする。skinCluster は bake後に作成するため、targetへ保持される。

    Args:
        node: autoRemesherNode名。Noneの場合は選択項目から解決する。
        transfer_uvs: sourceの全UV setをclosest pointで転送するか。
        transfer_skin: sourceにskinがある場合にskinを転送するか。

    Returns:
        確定されたtarget transformのフルパス。

    Raises:
        ValueError: 接続または引数が不正な場合。
        RuntimeError: Undoが無効な場合、またはMaya処理に失敗した場合。
    """
    if not isinstance(transfer_uvs, bool) or not isinstance(transfer_skin, bool):
        raise ValueError("transfer_uvs と transfer_skin はboolで指定してください。")

    remesh_node = _resolve_finalize_node(node)
    source_shape, target_shape, target_transform = _resolve_finalize_meshes(remesh_node)
    skin_data = _capture_finalize_skin(source_shape, target_shape) if transfer_skin else None
    source_uv_sets = (cmds.polyUVSet(source_shape, query=True, allUVSets=True) or []) if transfer_uvs else []
    undo_utils.require_enabled("AutoRemesher Finalize")

    original_selection = cmds.ls(selection=True, long=True) or []
    failed = False
    cmds.undoInfo(openChunk=True, chunkName=_FINALIZE_CHUNK_NAME)
    try:
        if transfer_uvs and source_uv_sets:
            _transfer_finalize_uvs(source_shape, target_shape)

        # skin転送前なのでtargetの生成履歴を全て確定できる。AutoRemesherは
        # Mayaの bakePartialHistory が対応しないため、constructionHistory削除で
        # 現在評価値を残してtargetだけを焼く（source historyは触らない）。
        cmds.delete(target_transform, constructionHistory=True)
        if skin_data is not None:
            skin_io.transfer(
                target_transform,
                skin_data,
                surface_association="closestPoint",
                manage_undo=False,
            )

        # bake後に孤立したnodeが残るMaya版では、出力接続がない場合だけ除去する。
        if cmds.objExists(remesh_node):
            destinations = cmds.listConnections(remesh_node + ".outMesh", source=False, destination=True, plugs=True) or []
            if not destinations:
                cmds.delete(remesh_node)
            elif destinations:
                raise RuntimeError("target historyをAutoRemesherから切り離せません。")
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
    return target_transform


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
        widthHeight=(320, 280),
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

    sharp_edge_degrees_field = cmds.floatSliderGrp(
        label="Sharp Edge Degrees",
        field=True,
        minValue=0.0,
        maxValue=180.0,
        value=90.0,
        annotation="シャープエッジと判定する角度（度）",
    )
    smooth_normal_degrees_field = cmds.floatSliderGrp(
        label="Smooth Normal Degrees",
        field=True,
        minValue=0.0,
        maxValue=180.0,
        value=0.0,
        annotation="法線を平滑化する角度（度）",
    )

    cmds.separator(height=10, style="in")

    def _on_create(*_args):
        target_count = cmds.intFieldGrp(target_count_field, query=True, value1=True)
        adaptivity = cmds.floatSliderGrp(adaptivity_field, query=True, value=True)
        edge_scaling = cmds.floatFieldGrp(edge_scaling_field, query=True, value1=True)
        model_type = cmds.optionMenuGrp(model_type_field, query=True, select=True) - 1
        sharp_edge_degrees = cmds.floatSliderGrp(sharp_edge_degrees_field, query=True, value=True)
        smooth_normal_degrees = cmds.floatSliderGrp(smooth_normal_degrees_field, query=True, value=True)

        node = create_remesh_node(
            target_count=target_count,
            adaptivity=adaptivity,
            edge_scaling=edge_scaling,
            model_type=model_type,
            sharp_edge_degrees=sharp_edge_degrees,
            smooth_normal_degrees=smooth_normal_degrees,
        )
        if node and cmds.window(_OPTIONS_WINDOW_NAME, exists=True):
            cmds.deleteUI(_OPTIONS_WINDOW_NAME, window=True)

    cmds.button(label="Create Node", command=_on_create, height=30)

    cmds.showWindow(window)
    return window
