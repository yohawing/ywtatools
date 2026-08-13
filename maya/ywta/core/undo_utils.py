"""Undo保証を持つMaya変更操作の共通guard。"""

from __future__ import absolute_import

import maya.cmds as cmds


def require_enabled(operation):
    """Maya Undoが無効ならscene編集前に処理を拒否する。"""
    if not isinstance(operation, str) or not operation.strip():
        raise ValueError("operation名を指定してください。")
    if not cmds.undoInfo(query=True, state=True):
        raise RuntimeError("Maya Undoを有効にしてから実行してください: {}".format(operation))
