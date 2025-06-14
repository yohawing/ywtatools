"""
Settings Manager

設定管理クラスを提供します。
デフォルト設定とユーザー設定を統合し、設定値へのアクセスを提供します。
"""

from __future__ import annotations

import os
import json
import logging
import shutil
from pathlib import Path
from typing import Any, Dict, Optional, Union, List, Tuple

from .base_config import BaseConfig, ConfigValue

logger = logging.getLogger(__name__)


class SettingsManager(BaseConfig):
    """YWTA Tools設定管理クラス

    デフォルト設定とユーザー設定を統合し、設定値へのアクセスを提供します。
    設定値の優先順位: 環境変数 > ユーザー設定 > デフォルト設定
    """

    _instance: Optional[SettingsManager] = None

    def __init__(
        self,
        user_config_file: Optional[Union[str, Path]] = None,
        default_config_file: Optional[Union[str, Path]] = None,
    ):
        # ユーザー設定ファイルのパスを決定
        if user_config_file is None:
            user_config_file = self._get_user_config_path()
        self.user_config_file = Path(user_config_file)

        # デフォルト設定ファイルのパスを決定
        if default_config_file is None:
            default_config_file = self._get_default_config_path()
        self.default_config_file = Path(default_config_file)

        # ユーザー設定ディレクトリが存在しない場合は作成
        self.user_config_file.parent.mkdir(parents=True, exist_ok=True)

        # デフォルト設定を読み込み
        self._default_config_data: Dict[str, Any] = {}
        if self.default_config_file.exists():
            self._load_json_file(self.default_config_file, self._default_config_data)
        else:
            logger.warning(
                f"デフォルト設定ファイルが見つかりません: {self.default_config_file}"
            )

        # ユーザー設定ファイルが存在しない場合は作成
        if not self.user_config_file.exists():
            self._create_initial_user_config()

        # BaseConfigの初期化（ユーザー設定ファイルを使用）
        super().__init__(self.user_config_file)

        # QSettings互換性
        self._qsettings = None
        self._init_qsettings()

    @classmethod
    def get_instance(
        cls,
        user_config_file: Optional[Union[str, Path]] = None,
        default_config_file: Optional[Union[str, Path]] = None,
    ) -> SettingsManager:
        """シングルトンインスタンスを取得"""
        if cls._instance is None:
            cls._instance = cls(user_config_file, default_config_file)
        return cls._instance

    def _get_user_config_path(self) -> Path:
        """ユーザー設定ファイルパスを取得"""
        try:
            import maya.cmds as cmds

            maya_app_dir = Path(cmds.internalVar(userAppDir=True))
            config_dir = maya_app_dir / "ywta_tools"
        except ImportError:
            config_dir = Path.home() / ".ywta_tools"

        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir / "user_config.json"

    def _get_default_config_path(self) -> Path:
        """デフォルト設定ファイルパスを取得"""
        # モジュールのディレクトリを取得
        module_dir = Path(__file__).parent
        return module_dir / "default_config.json"

    def _create_initial_user_config(self) -> None:
        """初期ユーザー設定ファイルを作成"""
        # 空の設定ファイルを作成
        empty_config = {
            "user": {
                "name": "",
                "email": "",
                "preferences": {"recent_projects": [], "recent_files": []},
            }
        }

        with open(self.user_config_file, "w", encoding="utf-8") as f:
            json.dump(empty_config, f, indent=2, ensure_ascii=False)

        logger.info(f"初期ユーザー設定ファイルを作成しました: {self.user_config_file}")

    def _load_json_file(self, file_path: Path, target_dict: Dict[str, Any]) -> None:
        """JSONファイルを読み込み、辞書に格納"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                target_dict.clear()
                target_dict.update(data)
        except Exception as e:
            logger.error(f"設定ファイルの読み込みに失敗しました {file_path}: {e}")
            raise

    def _init_qsettings(self):
        """QSettings互換性のための初期化"""
        try:
            try:
                from PySide6.QtCore import QSettings
            except ImportError:
                try:
                    from PySide2.QtCore import QSettings
                except ImportError:
                    from PySide.QtCore import QSettings

            self._qsettings = QSettings("Chad Vernon", "CMT")
        except ImportError:
            logger.warning("Qt not available, QSettings compatibility disabled")
            self._qsettings = None

    def _initialize_config_values(self) -> None:
        """基本的な設定値を初期化

        デフォルト設定ファイルから設定値を読み込み、ConfigValueインスタンスを作成します。
        """
        # デフォルト設定ファイルから設定値を読み込み
        self._register_config_values_from_dict(self._default_config_data)

        # 既存設定との互換性のための明示的な設定
        self.add_config_value(
            ConfigValue(
                key="documentation.root_url",
                default="",
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

    def _register_config_values_from_dict(
        self, config_dict: Dict[str, Any], prefix: str = ""
    ) -> None:
        """辞書から再帰的に設定値を登録"""
        for key, value in config_dict.items():
            full_key = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                # 辞書の場合は再帰的に処理
                self._register_config_values_from_dict(value, full_key)
            else:
                # 辞書でない場合は設定値として登録
                if full_key not in self._config_values:
                    self.add_config_value(
                        ConfigValue(
                            key=full_key,
                            default=value,
                            description=f"設定値: {full_key}",
                        )
                    )

    def get(self, key: str, default: Any = None) -> Any:
        """設定値を取得

        優先順位: 環境変数 > ユーザー設定 > デフォルト設定 > 指定されたデフォルト値
        """
        # ConfigValueが登録されている場合はそれを使用
        if key in self._config_values:
            return self._config_values[key].get(self._config_data)

        # ユーザー設定から取得
        user_value = self._get_from_nested_dict(self._config_data, key)
        if user_value is not None:
            return user_value

        # デフォルト設定から取得
        default_value = self._get_from_nested_dict(self._default_config_data, key)
        if default_value is not None:
            return default_value

        # 指定されたデフォルト値を返す
        return default

    def _get_from_nested_dict(self, data: Dict[str, Any], key: str) -> Any:
        """ネストされた辞書から値を取得"""
        keys = key.split(".")
        value = data
        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return None

    def reset_to_default(self, key: str = None) -> None:
        """設定値をデフォルトにリセット

        keyが指定されていない場合は、すべての設定値をリセットします。
        """
        if key is None:
            # すべての設定値をリセット
            self._config_data.clear()
            self.save_config()
            logger.info("すべての設定値をデフォルトにリセットしました")
        else:
            # 指定された設定値をリセット
            keys = key.split(".")
            if len(keys) == 1:
                if key in self._config_data:
                    del self._config_data[key]
            else:
                parent_key = ".".join(keys[:-1])
                last_key = keys[-1]
                parent = self._get_from_nested_dict(self._config_data, parent_key)
                if (
                    parent is not None
                    and isinstance(parent, dict)
                    and last_key in parent
                ):
                    del parent[last_key]
            self.save_config()
            logger.info(f"設定値 '{key}' をデフォルトにリセットしました")

    def export_settings(self, file_path: Union[str, Path]) -> None:
        """設定をエクスポート

        現在の設定（デフォルト設定とユーザー設定を統合したもの）をファイルにエクスポートします。
        """
        file_path = Path(file_path)

        # デフォルト設定とユーザー設定を統合
        merged_config = self._default_config_data.copy()
        self._merge_dict(merged_config, self._config_data)

        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(merged_config, f, indent=2, ensure_ascii=False)
            logger.info(f"設定をエクスポートしました: {file_path}")
        except Exception as e:
            logger.error(f"設定のエクスポートに失敗しました: {e}")
            raise

    def import_settings(self, file_path: Union[str, Path]) -> None:
        """設定をインポート

        ファイルから設定をインポートし、現在のユーザー設定を上書きします。
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"設定ファイルが見つかりません: {file_path}")

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                imported_config = json.load(f)

            # インポートした設定をユーザー設定に適用
            self._config_data.clear()
            self._config_data.update(imported_config)
            self.save_config()
            logger.info(f"設定をインポートしました: {file_path}")
        except Exception as e:
            logger.error(f"設定のインポートに失敗しました: {e}")
            raise

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

    def get_all_settings(self) -> Dict[str, Any]:
        """すべての設定値を取得

        デフォルト設定とユーザー設定を統合した結果を返します。
        """
        # デフォルト設定をコピー
        result = self._default_config_data.copy()

        # ユーザー設定を統合
        self._merge_dict(result, self._config_data)

        return result

    def get_modified_settings(self) -> Dict[str, Tuple[Any, Any]]:
        """変更された設定値を取得

        ユーザーが変更した設定値（デフォルト値と異なる値）を返します。
        戻り値は {key: (default_value, current_value)} の形式です。
        """
        result = {}

        def compare_dicts(default_dict, user_dict, prefix=""):
            for key, default_value in default_dict.items():
                full_key = f"{prefix}.{key}" if prefix else key

                if key in user_dict:
                    user_value = user_dict[key]

                    if isinstance(default_value, dict) and isinstance(user_value, dict):
                        # 再帰的に辞書を比較
                        compare_dicts(default_value, user_value, full_key)
                    elif default_value != user_value:
                        # 値が異なる場合は結果に追加
                        result[full_key] = (default_value, user_value)

        compare_dicts(self._default_config_data, self._config_data)
        return result


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


def reset_setting(key: str = None) -> None:
    """設定値をデフォルトにリセット（便利関数）"""
    get_settings_manager().reset_to_default(key)


def export_settings(file_path: Union[str, Path]) -> None:
    """設定をエクスポート（便利関数）"""
    get_settings_manager().export_settings(file_path)


def import_settings(file_path: Union[str, Path]) -> None:
    """設定をインポート（便利関数）"""
    get_settings_manager().import_settings(file_path)


def save_settings() -> None:
    """設定を保存（便利関数）

    現在の設定をユーザー設定ファイルに保存します。
    """
    get_settings_manager().save_config()


def add_callback(key: str, callback: callable) -> None:
    """設定値変更時のコールバックを追加（便利関数）

    Args:
        key: 設定キー
        callback: コールバック関数。引数として (key, value) を受け取る必要があります。

    Example:
        ```python
        def on_theme_changed(key, value):
            print(f"テーマが変更されました: {value}")
            # UIの更新など

        # コールバックを登録
        add_callback("ui.theme.primary_color", on_theme_changed)

        # 設定を変更（コールバックが呼び出される）
        set_setting("ui.theme.primary_color", "#FF0000")
        ```
    """
    get_settings_manager().add_callback(key, callback)


def remove_callback(key: str, callback: callable) -> None:
    """コールバックを削除（便利関数）

    Args:
        key: 設定キー
        callback: 削除するコールバック関数
    """
    get_settings_manager().remove_callback(key, callback)
