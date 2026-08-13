"""選択中心へjointを安全に作成する。"""

import maya.cmds as cmds

from ywta.core import undo_utils


def _validated_node_name(name, inherited_namespace=""):
    """Maya正規名と作成先namespaceを検証し、絶対名を返す。"""
    if not isinstance(name, str) or not name.strip():
        raise ValueError("node名が不正です。")
    name = name.strip().lstrip(":")
    if ":" not in name and inherited_namespace:
        name = inherited_namespace.strip(":") + ":" + name
    segments = name.split(":")
    if any(not segment or cmds.namespace(validateName=segment) != segment for segment in segments):
        raise ValueError("Mayaが自動変換するnode名は使用できません: {}".format(name))
    if len(segments) > 1:
        namespace = ":".join(segments[:-1])
        if not cmds.namespace(exists=":" + namespace):
            raise ValueError("作成先namespaceがありません: {}".format(namespace))
    return ":" + name


def _selection_center(selection):
    """選択全体のworld bounding box中心、空選択なら原点を返す。"""
    if not selection:
        return [0.0, 0.0, 0.0]
    bounds = cmds.exactWorldBoundingBox(selection, ignoreInvisible=False)
    if len(bounds) != 6:
        raise RuntimeError("選択範囲を取得できません。")
    return [(bounds[index] + bounds[index + 3]) * 0.5 for index in range(3)]


def _selected_parent_joint():
    """選択順の最後がjointなら一意なロングパスを返す。"""
    objects = cmds.ls(selection=True, objectsOnly=True, long=True) or []
    if not objects or cmds.nodeType(objects[-1]) != "joint":
        return None
    parent = objects[-1]
    if cmds.referenceQuery(parent, isNodeReferenced=True):
        raise ValueError("参照jointの子は作成できません: {}".format(parent))
    return parent


def create_joint_at_selection(name="joint", parent_to_last_joint=True):
    """選択中心または原点へjointを単一Undoで作成する。

    Args:
        name: 作成するjoint名。
        parent_to_last_joint: 最後の選択objectがjointなら子として作成する。

    Returns:
        作成したjointのロングパス。
    """
    if not isinstance(parent_to_last_joint, bool):
        raise ValueError("parent_to_last_jointはboolで指定してください。")
    selection = cmds.ls(selection=True, flatten=True, long=True) or []
    center = _selection_center(selection)
    parent = _selected_parent_joint() if parent_to_last_joint else None
    parent_namespace = parent.rsplit("|", 1)[-1].rpartition(":")[0] if parent else ""
    name = _validated_node_name(name, inherited_namespace=parent_namespace)

    undo_utils.require_enabled("Create Joint at Selection")
    cmds.undoInfo(openChunk=True, chunkName="YWTA Create Joint at Selection")
    failed = False
    try:
        cmds.select(clear=True)
        joint = cmds.joint(name=name, position=center)
        if parent:
            joint = cmds.parent(joint, parent)[0]
        joint = (cmds.ls(joint, long=True, type="joint") or [joint])[0]
        cmds.select(joint, replace=True)
    except Exception:
        failed = True
        raise
    finally:
        cmds.undoInfo(closeChunk=True)
        if failed:
            cmds.undo()
    return joint


def create_joint_from_selected_verts():
    """選択頂点のworld位置平均へjointを1つ作成する互換入口。"""
    vertices = cmds.filterExpand(selectionMask=31, expand=True) or []
    if not vertices:
        cmds.warning("頂点が選択されていません。")
        return None
    return _create_joints_at_positions([_average_position(vertices)])[0]


def create_joint_from_selected_faces():
    """選択faceごとの頂点平均へjointを1つずつ作成する互換入口。"""
    faces = cmds.filterExpand(selectionMask=34, expand=True) or []
    if not faces:
        cmds.warning("faceが選択されていません。")
        return None
    positions = []
    for face in faces:
        vertices = cmds.polyListComponentConversion(face, toVertex=True) or []
        vertices = cmds.filterExpand(vertices, selectionMask=31, expand=True) or []
        if not vertices:
            raise RuntimeError("face頂点を解決できません: {}".format(face))
        positions.append(_average_position(vertices))
    return _create_joints_at_positions(positions)


def create_joint_from_selected_component():
    """旧component APIを頂点優先で振り分ける。"""
    if cmds.filterExpand(selectionMask=31, expand=True):
        return create_joint_from_selected_verts()
    if cmds.filterExpand(selectionMask=34, expand=True):
        return create_joint_from_selected_faces()
    cmds.warning("頂点またはfaceが選択されていません。")
    return None


def _average_position(components):
    """component列のworld位置平均を返す。"""
    positions = [cmds.pointPosition(component, world=True) for component in components]
    return [sum(position[axis] for position in positions) / len(positions) for axis in range(3)]


def _create_joints_at_positions(positions):
    """world位置列へjointを1 transactionで作成する。"""
    undo_utils.require_enabled("Create Joints from Components")
    cmds.undoInfo(openChunk=True, chunkName="YWTA Create Joints from Components")
    failed = False
    try:
        created = []
        for position in positions:
            cmds.select(clear=True)
            created.append(cmds.joint(name="joint", position=position))
        created = [(cmds.ls(joint, long=True, type="joint") or [joint])[0] for joint in created]
        cmds.select(created, replace=True)
    except Exception:
        failed = True
        raise
    finally:
        cmds.undoInfo(closeChunk=True)
        if failed:
            cmds.undo()
    return created
