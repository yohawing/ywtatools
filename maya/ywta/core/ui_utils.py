"""
UI Utilities

Mayaのユーザーインターフェース操作に関連するユーティリティクラスと関数を提供します。
これらのクラスと関数は、UIの作成、管理、操作などの一般的なタスクを簡素化します。
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import logging
import os

import maya.cmds as cmds

logger = logging.getLogger(__name__)

# PySide2とPySide6の両方をサポート
try:
    from PySide6.QtCore import QSettings
except ImportError:
    from PySide2.QtCore import QSettings


class BaseTreeNode(object):
    """QAbstractItemModelで使用するための階層機能を含む基本ツリーノード"""

    def __init__(self, parent=None):
        self.children = []
        self._parent = parent

        if parent is not None:
            parent.add_child(self)

    def add_child(self, child):
        """ノードに子を追加します。

        :param child: 追加する子ノード
        """
        if child not in self.children:
            self.children.append(child)

    def remove(self):
        """このノードとそのすべての子をツリーから削除します。"""
        if self._parent:
            row = self.row()
            self._parent.children.pop(row)
            self._parent = None
        for child in self.children:
            child.remove()

    def child(self, row):
        """指定されたインデックスの子を取得します。

        :param row: 子のインデックス
        :return: 指定されたインデックスのツリーノード、またはインデックスが範囲外の場合はNone
        """
        try:
            return self.children[row]
        except IndexError:
            return None

    def child_count(self):
        """ノード内の子の数を取得します"""
        return len(self.children)

    def parent(self):
        """ノードの親を取得します"""
        return self._parent

    def row(self):
        """親に対するノードのインデックスを取得します"""
        if self._parent is not None:
            return self._parent.children.index(self)
        return 0

    def data(self, column):
        """テーブル表示データを取得します"""
        return ""


class SingletonWindowMixin(object):
    """ウィンドウのインスタンスを1つだけ許可するQWidgetベースのウィンドウで使用するミックスイン"""

    _window_instance = None

    @classmethod
    def show_window(cls):
        if not cls._window_instance:
            cls._window_instance = cls()
        cls._window_instance.show()
        cls._window_instance.raise_()
        cls._window_instance.activateWindow()

    def closeEvent(self, event):
        self._window_instance = None
        event.accept()


def get_icon_path(name):
    """指定されたアイコン名のパスを取得します。

    :param name: アイコンディレクトリ内のアイコンの名前
    :return: アイコンへのフルパス、または存在しない場合はNone
    """
    icon_directory = os.path.join(os.path.dirname(__file__), "..", "..", "..", "icons")
    image_extensions = ["png", "svg", "jpg", "jpeg"]
    for root, dirs, files in os.walk(icon_directory):
        for ext in image_extensions:
            full_path = os.path.join(root, "{0}.{1}".format(name, ext))
            if os.path.exists(full_path):
                return os.path.normpath(full_path)
    return None
