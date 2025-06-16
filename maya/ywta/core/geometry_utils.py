"""
Geometry Utilities

ジオメトリ操作、数学計算、空間変換に関連するユーティリティ関数を提供します。
これらの関数は、3D空間での計算や変換を簡素化します。
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import logging

import maya.cmds as cmds
import maya.api.OpenMaya as OpenMaya2

logger = logging.getLogger(__name__)


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

    source_point = OpenMaya2.MPoint(pos1[0], pos1[1], pos1[2])
    target_point = OpenMaya2.MPoint(pos2[0], pos2[1], pos2[2])
    return target_point - source_point


def get_bounding_box(node):
    """ノードのバウンディングボックスを取得します

    :param node: バウンディングボックスを取得するノード
    :return: (min_x, min_y, min_z, max_x, max_y, max_z)のタプル
    """
    bbox = cmds.exactWorldBoundingBox(node)
    return bbox


def get_center_point(node):
    """ノードの中心点を取得します

    :param node: 中心点を取得するノード
    :return: (x, y, z)の中心点座標
    """
    bbox = get_bounding_box(node)
    center_x = (bbox[0] + bbox[3]) / 2.0
    center_y = (bbox[1] + bbox[4]) / 2.0
    center_z = (bbox[2] + bbox[5]) / 2.0
    return (center_x, center_y, center_z)


def create_vector(x, y, z):
    """指定された成分からMVectorを作成します

    :param x: X成分
    :param y: Y成分
    :param z: Z成分
    :return: MVector
    """
    return OpenMaya2.MVector(x, y, z)


def normalize_vector(vector):
    """ベクトルを正規化します

    :param vector: 正規化するベクトル（MVectorまたは3要素のタプル/リスト）
    :return: 正規化されたMVector
    """
    if isinstance(vector, (tuple, list)):
        vector = OpenMaya2.MVector(vector[0], vector[1], vector[2])

    return vector.normalize()


def dot_product(vector1, vector2):
    """2つのベクトルのドット積を計算します

    :param vector1: 最初のベクトル（MVectorまたは3要素のタプル/リスト）
    :param vector2: 2番目のベクトル（MVectorまたは3要素のタプル/リスト）
    :return: ドット積の結果
    """
    if isinstance(vector1, (tuple, list)):
        vector1 = OpenMaya2.MVector(vector1[0], vector1[1], vector1[2])
    if isinstance(vector2, (tuple, list)):
        vector2 = OpenMaya2.MVector(vector2[0], vector2[1], vector2[2])

    return vector1 * vector2


def cross_product(vector1, vector2):
    """2つのベクトルのクロス積を計算します

    :param vector1: 最初のベクトル（MVectorまたは3要素のタプル/リスト）
    :param vector2: 2番目のベクトル（MVectorまたは3要素のタプル/リスト）
    :return: クロス積の結果（MVector）
    """
    if isinstance(vector1, (tuple, list)):
        vector1 = OpenMaya2.MVector(vector1[0], vector1[1], vector1[2])
    if isinstance(vector2, (tuple, list)):
        vector2 = OpenMaya2.MVector(vector2[0], vector2[1], vector2[2])

    return vector1 ^ vector2
