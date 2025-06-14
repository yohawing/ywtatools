"""
Node Utilities

Mayaのノード操作に関連するユーティリティ関数を提供します。
これらの関数は、ノードの取得、操作、変換などの一般的なタスクを簡素化します。
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import logging

import maya.cmds as cmds

logger = logging.getLogger(__name__)


def get_shape(node, intermediate=False):
    """トランスフォームのシェイプノードを取得します。

    これは、ノードがシェイプノードかトランスフォームかを確認する必要がない場合に便利です。
    シェイプノードまたはトランスフォームを渡すと、関数はシェイプノードを返します。

    :param node: ノード名
    :param intermediate: 中間シェイプを取得する場合はTrue
    :return: シェイプノード名
    """
    if cmds.objectType(node, isAType="transform"):
        shapes = cmds.listRelatives(node, shapes=True, path=True)
        if not shapes:
            shapes = []
        for shape in shapes:
            is_intermediate = cmds.getAttr("{}.intermediateObject".format(shape))
            if (
                intermediate
                and is_intermediate
                and cmds.listConnections(shape, source=False)
            ):
                return shape
            elif not intermediate and not is_intermediate:
                return shape
        if shapes:
            return shapes[0]
    elif cmds.nodeType(node) in ["mesh", "nurbsCurve", "nurbsSurface"]:
        is_intermediate = cmds.getAttr("{}.intermediateObject".format(node))
        if is_intermediate and not intermediate:
            node = cmds.listRelatives(node, parent=True, path=True)[0]
            return get_shape(node)
        else:
            return node
    return None


def get_node_in_namespace_hierarchy(node, namespace=None, shape=False):
    """指定された名前空間とすべてのネストされた名前空間から指定されたノードを検索します。

    :param node: ノード名
    :param namespace: ルート名前空間
    :param shape: シェイプノードを取得する場合はTrue、トランスフォームを取得する場合はFalse
    :return: 適切な名前空間内のノード
    """
    if shape and node and cmds.objExists(node):
        node = get_shape(node)

    if node and cmds.objExists(node):
        return node

    if node and namespace:
        # 名前空間または子名前空間に存在するかどうかを確認
        namespaces = [namespace.replace(":", "")]
        namespaces += cmds.namespaceInfo(namespace, r=True, lon=True) or []
        for namespace in namespaces:
            namespaced_node = "{0}:{1}".format(namespace, node)
            if shape:
                namespaced_node = get_shape(namespaced_node)
            if namespaced_node and cmds.objExists(namespaced_node):
                return namespaced_node
    return None


def distance(node1=None, node2=None):
    """2つのノード間の距離を計算します

    :param node1: 最初のノード
    :param node2: 2番目のノード
    :return: 距離
    """
    if node1 is None or node2 is None:
        # デフォルトで選択を使用
        selection = cmds.ls(sl=True, type="transform")
        if len(selection) != 2:
            raise RuntimeError("2つのトランスフォームを選択してください。")
        node1, node2 = selection

    pos1 = cmds.xform(node1, query=True, worldSpace=True, translation=True)
    pos2 = cmds.xform(node2, query=True, worldSpace=True, translation=True)

    import maya.api.OpenMaya as OpenMaya2

    pos1 = OpenMaya2.MPoint(pos1[0], pos1[1], pos1[2])
    pos2 = OpenMaya2.MPoint(pos2[0], pos2[1], pos2[2])
    return pos1.distanceTo(pos2)


def vector_to(source=None, target=None):
    """2つのノード間のベクトルを計算します

    :param source: 始点ノード
    :param target: 終点ノード
    :return: MVector (API2)
    """
    if source is None or target is None:
        # デフォルトで選択を使用
        selection = cmds.ls(sl=True, type="transform")
        if len(selection) != 2:
            raise RuntimeError("2つのトランスフォームを選択してください。")
        source, target = selection

    pos1 = cmds.xform(source, query=True, worldSpace=True, translation=True)
    pos2 = cmds.xform(target, query=True, worldSpace=True, translation=True)

    import maya.api.OpenMaya as OpenMaya2

    source = OpenMaya2.MPoint(pos1[0], pos1[1], pos1[2])
    target = OpenMaya2.MPoint(pos2[0], pos2[1], pos2[2])
    return target - source
