"""
YWTA Tools Settings

新しい設定システムとの統合と後方互換性を提供します。
"""

from .config.settings_manager import get_settings_manager

# 設定マネージャーのインスタンスを取得
_settings = get_settings_manager()


# 後方互換性のための定数（プロパティとして動的に取得）
@property
def DOCUMENTATION_ROOT():
    return _settings.DOCUMENTATION_ROOT


@DOCUMENTATION_ROOT.setter
def DOCUMENTATION_ROOT(value):
    _settings.DOCUMENTATION_ROOT = value


@property
def ENABLE_PLUGINS():
    return _settings.ENABLE_PLUGINS


@ENABLE_PLUGINS.setter
def ENABLE_PLUGINS(value):
    _settings.ENABLE_PLUGINS = value


# モジュールレベルでのプロパティアクセスを可能にする
import sys

current_module = sys.modules[__name__]


class SettingsModule:
    """設定モジュールのラッパークラス"""

    def __init__(self, module):
        self._module = module
        self._settings = get_settings_manager()

    def __getattr__(self, name):
        if name == "DOCUMENTATION_ROOT":
            return self._settings.DOCUMENTATION_ROOT
        elif name == "ENABLE_PLUGINS":
            return self._settings.ENABLE_PLUGINS
        else:
            return getattr(self._module, name)

    def __setattr__(self, name, value):
        if name.startswith("_"):
            super().__setattr__(name, value)
        elif name == "DOCUMENTATION_ROOT":
            self._settings.DOCUMENTATION_ROOT = value
        elif name == "ENABLE_PLUGINS":
            self._settings.ENABLE_PLUGINS = value
        else:
            setattr(self._module, name, value)


# モジュールを置き換え
sys.modules[__name__] = SettingsModule(current_module)
