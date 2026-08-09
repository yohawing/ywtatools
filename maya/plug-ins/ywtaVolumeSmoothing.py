"""YWTA RustメッシュスムージングコマンドのMayaプラグイン入口。"""

import maya.api.OpenMaya as om2

from ywta.mesh.volume_smoothing import COMMAND_NAME, VolumeSmoothingCommand


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


def uninitializePlugin(plugin_object):
    """コマンドをMayaから解除する。"""
    plugin = om2.MFnPlugin(plugin_object)
    try:
        plugin.deregisterCommand(COMMAND_NAME)
    except RuntimeError:
        # 二重アンロード時もプラグインを安全に解除する。
        pass
