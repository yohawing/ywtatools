"""
Maya API Utilities

Maya APIを使用するための便利なユーティリティ関数を提供します。
これらの関数は、Maya APIの複雑さを抽象化し、一般的なタスクを簡素化します。
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import logging

import maya.cmds as cmds
import maya.OpenMaya as OpenMaya
import maya.OpenMayaAnim as OpenMayaAnim
import maya.api.OpenMaya as OpenMaya2

logger = logging.getLogger(__name__)


def get_mobject(node):
    """指定されたノードのMObjectを取得します。

    :param node: ノード名
    :return: MObject
    """
    selection_list = OpenMaya2.MSelectionList()
    selection_list.add(node)
    mobject = selection_list.getDependNode(0)
    return mobject


def get_dag_path(node):
    """指定されたノードのMDagPathを取得します。

    :param node: ノード名
    :return: MDagPath
    """
    selection_list = OpenMaya2.MSelectionList()
    selection_list.add(node)
    path = selection_list.getDagPath(0)
    return path


def get_mfnmesh(mesh_name):
    """指定されたメッシュのMFnMeshを取得します。

    :param mesh_name: メッシュ名
    :return: MFnMesh
    """
    from maya.ywta.core.node_utils import get_shape

    mesh = get_shape(mesh_name)
    path = get_dag_path(mesh)
    return OpenMaya2.MFnMesh(path)


def get_points(mesh_name, space=OpenMaya2.MSpace.kObject):
    """メッシュの頂点位置をMPointArrayとして取得します。

    :param mesh_name: メッシュ名
    :param space: 座標空間（デフォルトはオブジェクト空間）
    :return: MPointArray
    """
    fn_mesh = get_mfnmesh(mesh_name)
    points = fn_mesh.getPoints(space)
    return points


def set_points(mesh_name, points):
    """メッシュの頂点位置をMPointArrayで設定します。

    :param mesh_name: メッシュ名
    :param points: MPointArray
    """
    from maya.ywta.core.node_utils import get_shape

    mesh = get_shape(mesh_name)
    path = get_dag_path(mesh)
    fn_mesh = OpenMaya2.MFnMesh(path)
    fn_mesh.setPoints(points)


def get_mfnblendshapedeformer(blendshape_node_name):
    """指定されたブレンドシェイプノードのMFnBlendShapeDeformerを取得します。

    :param blendshape_node_name: ブレンドシェイプノード名
    :return: MFnBlendShapeDeformer
    """
    node = get_mobject(blendshape_node_name)
    blendShapeFn = OpenMayaAnim.MFnBlendShapeDeformer(node)
    return blendShapeFn


# MScriptUtil関連のユーティリティ
def get_int_ptr():
    """整数ポインタを作成します。

    :return: 整数ポインタ
    """
    util = OpenMaya.MScriptUtil()
    util.createFromInt(0)
    return util.asIntPtr()


def ptr_to_int(int_ptr):
    """整数ポインタから整数値を取得します。

    :param int_ptr: 整数ポインタ
    :return: 整数値
    """
    return OpenMaya.MScriptUtil.getInt(int_ptr)
