"""
Base Configuration Classes

設定システムの基盤となるクラスを定義します。
"""

from __future__ import annotations

import os
import json
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Union, Type, TypeVar, Generic
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ConfigError(Exception):
    """設定システムの基本例外クラス"""

    pass


class ValidationError(ConfigError):
    """設定値の検証エラー"""

    pass


class ConfigValue(Generic[T]):
    """設定値を表すクラス

    型安全性と検証機能を提供します。
    """

    def __init__(
        self,
        key: str,
        default: T,
        description: str = "",
        validator: Optional[callable] = None,
        env_var: Optional[str] = None,
    ):
        self.key = key
        self.default = default
        self.description = description
        self.validator = validator
        self.env_var = env_var or f"YWTA_{key.upper().replace('.', '_')}"
        self._value: Optional[T] = None
        self._is_set = False

    def get(self, config_data: Dict[str, Any] = None) -> T:
        """設定値を取得

        優先順位: 環境変数 > 設定ファイル > デフォルト値
        """
        if self._is_set:
            return self._value

        # 1. 環境変数をチェック
        env_value = os.environ.get(self.env_var)
        if env_value is not None:
            try:
                value = self._parse_env_value(env_value)
                if self.validator:
                    self.validator(value)
                self._value = value
                self._is_set = True
                return value
            except (ValueError, ValidationError) as e:
                logger.warning(f"Invalid environment variable {self.env_var}: {e}")

        # 2. 設定ファイルをチェック
        if config_data:
            keys = self.key.split(".")
            value = config_data
            try:
                for key in keys:
                    value = value[key]
                if self.validator:
                    self.validator(value)
                self._value = value
                self._is_set = True
                return value
            except (KeyError, TypeError, ValidationError):
                pass

        # 3. デフォルト値を使用
        if self.validator:
            self.validator(self.default)
        self._value = self.default
        self._is_set = True
        return self.default

    def set(self, value: T) -> None:
        """設定値を直接設定"""
        if self.validator:
            if not self.validator(value):
                raise ValidationError(f"Validation failed for {self.key}: {value}")
        self._value = value
        self._is_set = True

    def reset(self) -> None:
        """設定値をリセット"""
        self._value = None
        self._is_set = False

    def _parse_env_value(self, env_value: str) -> T:
        """環境変数の値を適切な型に変換"""
        if isinstance(self.default, bool):
            return env_value.lower() in ("true", "1", "yes", "on")
        elif isinstance(self.default, int):
            return int(env_value)
        elif isinstance(self.default, float):
            return float(env_value)
        elif isinstance(self.default, (list, dict)):
            return json.loads(env_value)
        else:
            return env_value


class BaseConfig(ABC):
    """設定クラスの基底クラス

    すべての設定クラスはこのクラスを継承する必要があります。
    """

    def __init__(self, config_file: Optional[Union[str, Path]] = None):
        self.config_file = Path(config_file) if config_file else None
        self._config_data: Dict[str, Any] = {}
        self._config_values: Dict[str, ConfigValue] = {}
        self._callbacks: Dict[str, list] = {}

        # 設定値を初期化
        self._initialize_config_values()

        # 設定ファイルを読み込み
        if self.config_file and self.config_file.exists():
            self.load_config()

    @abstractmethod
    def _initialize_config_values(self) -> None:
        """設定値を初期化する抽象メソッド

        サブクラスでこのメソッドを実装し、ConfigValueインスタンスを
        self._config_valuesに追加してください。
        """
        pass

    def add_config_value(self, config_value: ConfigValue) -> None:
        """設定値を追加"""
        self._config_values[config_value.key] = config_value

    def get(self, key: str, default: Any = None) -> Any:
        """設定値を取得"""
        if key in self._config_values:
            return self._config_values[key].get(self._config_data)

        # 直接辞書アクセス（後方互換性のため）
        keys = key.split(".")
        value = self._config_data
        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default

    def set(self, key: str, value: Any) -> None:
        """設定値を設定"""
        if key in self._config_values:
            self._config_values[key].set(value)
        else:
            # 直接辞書に設定（後方互換性のため）
            keys = key.split(".")
            data = self._config_data
            for k in keys[:-1]:
                if k not in data:
                    data[k] = {}
                data = data[k]
            data[keys[-1]] = value

        # コールバックを実行
        self._execute_callbacks(key, value)

    def reset(self, key: Optional[str] = None) -> None:
        """設定値をリセット"""
        if key is None:
            # すべての設定値をリセット
            for config_value in self._config_values.values():
                config_value.reset()
            self._config_data.clear()
        elif key in self._config_values:
            self._config_values[key].reset()
        else:
            # 直接辞書から削除
            keys = key.split(".")
            data = self._config_data
            try:
                for k in keys[:-1]:
                    data = data[k]
                del data[keys[-1]]
            except (KeyError, TypeError):
                pass

    def load_config(self, config_file: Optional[Union[str, Path]] = None) -> None:
        """設定ファイルを読み込み"""
        file_path = Path(config_file) if config_file else self.config_file
        if not file_path or not file_path.exists():
            logger.warning(f"Config file not found: {file_path}")
            return

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                if file_path.suffix.lower() == ".json":
                    self._config_data = json.load(f)
                else:
                    raise ConfigError(
                        f"Unsupported config file format: {file_path.suffix}, only .json is supported"
                    )

            logger.info(f"Config loaded from: {file_path}")

            # すべての設定値をリセットして再読み込み
            for config_value in self._config_values.values():
                config_value.reset()

        except Exception as e:
            logger.error(f"Failed to load config file {file_path}: {e}")
            raise ConfigError(f"Failed to load config file: {e}")

    def save_config(self, config_file: Optional[Union[str, Path]] = None) -> None:
        """設定ファイルに保存"""
        file_path = Path(config_file) if config_file else self.config_file
        if not file_path:
            raise ConfigError("No config file specified")

        # 現在の設定値を辞書に変換
        config_data = {}
        for key, config_value in self._config_values.items():
            if config_value._is_set:
                keys = key.split(".")
                data = config_data
                for k in keys[:-1]:
                    if k not in data:
                        data[k] = {}
                    data = data[k]
                data[keys[-1]] = config_value._value

        # 直接設定された値もマージ
        self._merge_dict(config_data, self._config_data)

        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                if file_path.suffix.lower() == ".json":
                    json.dump(config_data, f, indent=2, ensure_ascii=False)
                else:
                    raise ConfigError(
                        f"Unsupported config file format: {file_path.suffix}, only .json is supported"
                    )

            logger.info(f"Config saved to: {file_path}")

        except Exception as e:
            logger.error(f"Failed to save config file {file_path}: {e}")
            raise ConfigError(f"Failed to save config file: {e}")

    def add_callback(self, key: str, callback: callable) -> None:
        """設定値変更時のコールバックを追加"""
        if key not in self._callbacks:
            self._callbacks[key] = []
        self._callbacks[key].append(callback)

    def remove_callback(self, key: str, callback: callable) -> None:
        """コールバックを削除"""
        if key in self._callbacks and callback in self._callbacks[key]:
            self._callbacks[key].remove(callback)

    def _execute_callbacks(self, key: str, value: Any) -> None:
        """コールバックを実行"""
        if key in self._callbacks:
            for callback in self._callbacks[key]:
                try:
                    callback(key, value)
                except Exception as e:
                    logger.error(f"Callback error for key '{key}': {e}")

    def _merge_dict(self, target: dict, source: dict) -> None:
        """辞書を再帰的にマージ"""
        for key, value in source.items():
            if (
                key in target
                and isinstance(target[key], dict)
                and isinstance(value, dict)
            ):
                self._merge_dict(target[key], value)
            else:
                target[key] = value

    def get_all_config_values(self) -> Dict[str, Any]:
        """すべての設定値を取得"""
        result = {}
        for key, config_value in self._config_values.items():
            result[key] = config_value.get(self._config_data)
        return result

    def validate_all(self) -> None:
        """すべての設定値を検証"""
        for key, config_value in self._config_values.items():
            try:
                config_value.get(self._config_data)
            except ValidationError as e:
                raise ValidationError(f"Validation failed for '{key}': {e}")
