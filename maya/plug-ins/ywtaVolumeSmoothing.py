"""YWTA RustメッシュスムージングコマンドのMayaプラグイン入口。"""

import maya.api.OpenMaya as om2

from ywta.mesh.volume_smoothing import (
    BRUSH_CONTEXT_NAME,
    BRUSH_COMMIT_COMMAND_NAME,
    COMMAND_NAME,
    VolumeSmoothingBrushContextCommand,
    VolumeSmoothingBrushCommitCommand,
    VolumeSmoothingCommand,
)


def maya_useNewAPI():
    """MayaにPython API 2.0のMObjectを渡すよう通知する。"""
    pass


def initializePlugin(plugin_object):
    """コマンドをMayaへ登録する。"""
    plugin = om2.MFnPlugin(plugin_object, "yohawing", "1.0", "Any")
    plugin.registerCommand(
        COMMAND_NAME,
        VolumeSmoothingCommand.creator,
        VolumeSmoothingCommand.createSyntax,
    )
    plugin.registerCommand(
        BRUSH_COMMIT_COMMAND_NAME,
        VolumeSmoothingBrushCommitCommand.creator,
    )
    try:
        # Maya 2024 Python API 2.0のcontext登録は2引数版のみを公開する。
        plugin.registerContextCommand(BRUSH_CONTEXT_NAME, VolumeSmoothingBrushContextCommand.creator)
    except Exception:
        plugin.deregisterCommand(BRUSH_COMMIT_COMMAND_NAME)
        plugin.deregisterCommand(COMMAND_NAME)
        raise


def uninitializePlugin(plugin_object):
    """コマンドをMayaから解除する。"""
    plugin = om2.MFnPlugin(plugin_object)
    try:
        plugin.deregisterContextCommand(BRUSH_CONTEXT_NAME)
        plugin.deregisterCommand(BRUSH_COMMIT_COMMAND_NAME)
        plugin.deregisterCommand(COMMAND_NAME)
    except RuntimeError:
        # 二重アンロード時もプラグインを安全に解除する。
        pass
