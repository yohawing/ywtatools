"""選択中心へ基本objectを作成する。"""

import maya.cmds as cmds

from ywta.core import undo_utils
from ywta.rig.create_joint import _selection_center


OBJECT_CREATORS = {
    "null": ("null", lambda name: cmds.createNode("transform", name=name)),
    "locator": ("locator", lambda name: cmds.spaceLocator(name=name)[0]),
    "cube": ("cube", lambda name: cmds.polyCube(name=name)[0]),
    "sphere": ("sphere", lambda name: cmds.polySphere(name=name)[0]),
    "cylinder": ("cylinder", lambda name: cmds.polyCylinder(name=name)[0]),
    "plane": ("plane", lambda name: cmds.polyPlane(name=name)[0]),
}


def create_at_selection(kind, name=None):
    """基本objectを選択中心、または空選択時の原点へ作成する。

    Args:
        kind: null / locator / cube / sphere / cylinder / plane。
        name: 任意のnode名。省略時はkind名を使用する。

    Returns:
        作成したtransformのロングパス。
    """
    if kind not in OBJECT_CREATORS:
        raise ValueError("未対応のobject種別です: {}".format(kind))
    default_name, creator = OBJECT_CREATORS[kind]
    if name is None:
        name = default_name
    if not isinstance(name, str) or not name.strip() or "|" in name:
        raise ValueError("object名が不正です。")
    selection = cmds.ls(selection=True, flatten=True, long=True) or []
    center = _selection_center(selection)

    undo_utils.require_enabled("Create Object at Selection")
    cmds.undoInfo(openChunk=True, chunkName="YWTA Create {} at Selection".format(kind.title()))
    failed = False
    try:
        transform = creator(name.strip())
        cmds.xform(transform, worldSpace=True, translation=center)
        transform = (cmds.ls(transform, long=True, type="transform") or [transform])[0]
        cmds.select(transform, replace=True)
    except Exception:
        failed = True
        raise
    finally:
        cmds.undoInfo(closeChunk=True)
        if failed:
            cmds.undo()
    return transform


def create_null():
    """選択中心へnull transformを作成する。"""
    return create_at_selection("null")


def create_locator():
    """選択中心へlocatorを作成する。"""
    return create_at_selection("locator")


def create_cube():
    """選択中心へpoly cubeを作成する。"""
    return create_at_selection("cube")


def create_sphere():
    """選択中心へpoly sphereを作成する。"""
    return create_at_selection("sphere")


def create_cylinder():
    """選択中心へpoly cylinderを作成する。"""
    return create_at_selection("cylinder")


def create_plane():
    """選択中心へpoly planeを作成する。"""
    return create_at_selection("plane")
