"""
Configuration Schema

設定値のスキーマ定義と検証ルールを提供します。
"""

from typing import Any, Dict, List, Optional, Union, Callable
from .base_config import ValidationError


class ConfigSchema:
    """設定スキーマクラス

    設定値の型、制約、検証ルールを定義します。
    """

    def __init__(self):
        self.validators: Dict[str, List[Callable]] = {}
        self.constraints: Dict[str, Dict[str, Any]] = {}

    def add_validator(
        self, key: str, validator: Callable[[Any], bool], error_message: str = ""
    ) -> None:
        """バリデーターを追加

        Args:
            key: 設定キー
            validator: 検証関数（True/Falseを返す）
            error_message: エラーメッセージ
        """
        if key not in self.validators:
            self.validators[key] = []

        def wrapped_validator(value):
            if not validator(value):
                raise ValidationError(
                    error_message or f"Validation failed for {key}: {value}"
                )

        self.validators[key].append(wrapped_validator)

    def add_range_constraint(
        self,
        key: str,
        min_value: Optional[Union[int, float]] = None,
        max_value: Optional[Union[int, float]] = None,
    ) -> None:
        """数値範囲制約を追加"""

        def range_validator(value):
            if not isinstance(value, (int, float)):
                raise ValidationError(f"{key} must be a number, got {type(value)}")
            if min_value is not None and value < min_value:
                raise ValidationError(f"{key} must be >= {min_value}, got {value}")
            if max_value is not None and value > max_value:
                raise ValidationError(f"{key} must be <= {max_value}, got {value}")

        self.add_validator(key, lambda v: True, "")  # ダミー
        if key not in self.validators:
            self.validators[key] = []
        self.validators[key][-1] = range_validator

    def add_choice_constraint(self, key: str, choices: List[Any]) -> None:
        """選択肢制約を追加"""

        def choice_validator(value):
            if value not in choices:
                raise ValidationError(f"{key} must be one of {choices}, got {value}")

        self.add_validator(key, lambda v: True, "")  # ダミー
        if key not in self.validators:
            self.validators[key] = []
        self.validators[key][-1] = choice_validator

    def add_type_constraint(self, key: str, expected_type: type) -> None:
        """型制約を追加"""

        def type_validator(value):
            if not isinstance(value, expected_type):
                raise ValidationError(
                    f"{key} must be of type {expected_type.__name__}, got {type(value).__name__}"
                )

        self.add_validator(key, lambda v: True, "")  # ダミー
        if key not in self.validators:
            self.validators[key] = []
        self.validators[key][-1] = type_validator

    def add_path_constraint(
        self,
        key: str,
        must_exist: bool = False,
        must_be_file: bool = False,
        must_be_dir: bool = False,
    ) -> None:
        """パス制約を追加"""
        import os

        def path_validator(value):
            if not isinstance(value, str):
                raise ValidationError(
                    f"{key} must be a string path, got {type(value).__name__}"
                )

            if must_exist and not os.path.exists(value):
                raise ValidationError(f"{key} path does not exist: {value}")

            if must_be_file and not os.path.isfile(value):
                raise ValidationError(f"{key} must be a file: {value}")

            if must_be_dir and not os.path.isdir(value):
                raise ValidationError(f"{key} must be a directory: {value}")

        self.add_validator(key, lambda v: True, "")  # ダミー
        if key not in self.validators:
            self.validators[key] = []
        self.validators[key][-1] = path_validator

    def validate(self, key: str, value: Any) -> None:
        """設定値を検証"""
        if key in self.validators:
            for validator in self.validators[key]:
                validator(value)

    def validate_all(self, config_data: Dict[str, Any]) -> None:
        """すべての設定値を検証"""
        for key in self.validators:
            if key in config_data:
                self.validate(key, config_data[key])


# 共通バリデーター関数
def validate_url(value: str) -> bool:
    """URL形式の検証"""
    import re

    url_pattern = re.compile(
        r"^https?://"  # http:// or https://
        r"(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|"  # domain...
        r"localhost|"  # localhost...
        r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"  # ...or ip
        r"(?::\d+)?"  # optional port
        r"(?:/?|[/?]\S+)$",
        re.IGNORECASE,
    )
    return url_pattern.match(value) is not None


def validate_maya_version(value: str) -> bool:
    """Maya バージョン形式の検証 (例: "2024", "2023.5")"""
    import re

    version_pattern = re.compile(r"^\d{4}(?:\.\d+)?$")
    return version_pattern.match(value) is not None


def validate_log_level(value: str) -> bool:
    """ログレベルの検証"""
    valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    return value.upper() in valid_levels


def validate_color_hex(value: str) -> bool:
    """16進数カラーコードの検証 (#RRGGBB or #RGB)"""
    import re

    hex_pattern = re.compile(r"^#(?:[0-9a-fA-F]{3}){1,2}$")
    return hex_pattern.match(value) is not None


def validate_positive_number(value: Union[int, float]) -> bool:
    """正の数値の検証"""
    return isinstance(value, (int, float)) and value > 0


def validate_non_negative_number(value: Union[int, float]) -> bool:
    """非負の数値の検証"""
    return isinstance(value, (int, float)) and value >= 0


def validate_port_number(value: int) -> bool:
    """ポート番号の検証 (1-65535)"""
    return isinstance(value, int) and 1 <= value <= 65535


def validate_file_extension(value: str, allowed_extensions: List[str]) -> bool:
    """ファイル拡張子の検証"""
    import os

    _, ext = os.path.splitext(value.lower())
    return ext in [
        e.lower() if e.startswith(".") else f".{e.lower()}" for e in allowed_extensions
    ]
