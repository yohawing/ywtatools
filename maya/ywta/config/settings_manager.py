"""
Settings Manager

シンプルな設定管理クラスを提供します。
"""

from __future__ import annotations

import os
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Union

from .base_config import BaseConfig, ConfigValue

logger = logging.getLogger(__name__)


class SettingsManager(BaseConfig):
    """YWTA Tools設定管理クラス"""

    _instance: Optional[SettingsManager] = None

    def __init__(self, config_file: Optional[Union[str, Path]] = None):
        if config_file is None:
            config_file = self._get_default_config_path()

        super().__init__(config_file)

        # QSettings互換性
        self._qsettings = None
        self._init_qsettings()

    @classmethod
    def get_instance(
        cls, config_file: Optional[Union[str, Path]] = None
    ) -> SettingsManager:
        """シングルトンインスタンスを取得"""
        if cls._instance is None:
            cls._instance = cls(config_file)
        return cls._instance

    def _get_default_config_path(self) -> Path:
        """デフォルト設定ファイルパスを取得"""
        try:
            import maya.cmds as cmds

            maya_app_dir = Path(cmds.internalVar(userAppDir=True))
            config_dir = maya_app_dir / "ywta_tools"
        except ImportError:
            config_dir = Path.home() / ".ywta_tools"

        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir / "config.yaml"

    def _init_qsettings(self):
        """QSettings互換性のための初期化"""
        try:
            try:
                from PySide2.QtCore import QSettings
            except ImportError:
                from PySide.QtCore import QSettings

            self._qsettings = QSettings("Chad Vernon", "CMT")
        except ImportError:
            logger.warning("Qt not available, QSettings compatibility disabled")
            self._qsettings = None

    def _initialize_config_values(self) -> None:
        """基本的な設定値を初期化"""

        # 既存設定との互換性
        self.add_config_value(
            ConfigValue(
                key="documentation.root_url",
                default="https://chadmv.github.io/cmt/html",
                description="ドキュメントのルートURL",
                env_var="YWTA_DOCUMENTATION_ROOT",
            )
        )

        self.add_config_value(
            ConfigValue(
                key="plugins.enable_cpp_plugins",
                default=True,
                description="C++プラグインを有効にするかどうか",
                env_var="YWTA_ENABLE_PLUGINS",
            )
        )

        # UI設定
        self.add_config_value(
            ConfigValue(
                key="ui.icon_size", default=24, description="アイコンサイズ（ピクセル）"
            )
        )

        # ログ設定
        self.add_config_value(
            ConfigValue(key="logging.level", default="INFO", description="ログレベル")
        )

    # QSettings互換性メソッド
    def value(self, key: str, default_value: Any = None) -> Any:
        """QSettings.value()互換メソッド"""
        result = self.get(key, None)
        if result is not None:
            return result

        if self._qsettings:
            result = self._qsettings.value(key, None)
            if result is not None:
                return result

        return default_value

    def setValue(self, key: str, value: Any) -> None:
        """QSettings.setValue()互換メソッド"""
        self.set(key, value)

        if self._qsettings:
            self._qsettings.setValue(key, value)

    # 後方互換性プロパティ
    @property
    def DOCUMENTATION_ROOT(self) -> str:
        return self.get("documentation.root_url")

    @DOCUMENTATION_ROOT.setter
    def DOCUMENTATION_ROOT(self, value: str) -> None:
        self.set("documentation.root_url", value)

    @property
    def ENABLE_PLUGINS(self) -> bool:
        return self.get("plugins.enable_cpp_plugins")

    @ENABLE_PLUGINS.setter
    def ENABLE_PLUGINS(self, value: bool) -> None:
        self.set("plugins.enable_cpp_plugins", value)


# グローバルインスタンス
_settings_manager: Optional[SettingsManager] = None


def get_settings_manager() -> SettingsManager:
    """設定マネージャーのグローバルインスタンスを取得"""
    global _settings_manager
    if _settings_manager is None:
        _settings_manager = SettingsManager.get_instance()
    return _settings_manager


def get_setting(key: str, default: Any = None) -> Any:
    """設定値を取得（便利関数）"""
    return get_settings_manager().get(key, default)


def set_setting(key: str, value: Any) -> None:
    """設定値を設定（便利関数）"""
    get_settings_manager().set(key, value)
