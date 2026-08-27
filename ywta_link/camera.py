"""YWTA Common Camera v1 の型、JSON codec、validator。"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from .errors import ValidationError
from .registry import DEFAULT_REGISTRY

CAMERA_SCHEMA = "ywta.common.camera.v1"
CAMERA_FIELDS = frozenset(DEFAULT_REGISTRY.require_schema(CAMERA_SCHEMA))
FILM_FIT_VALUES = frozenset({"horizontal", "vertical", "fill", "overscan"})
GATE_FIT_VALUES = FILM_FIT_VALUES

_CAMERA_FIELDS_IN_ORDER = (
    "entity_ref",
    "transform",
    "time",
    "projection",
    "focal_length",
    "horizontal_aperture",
    "vertical_aperture",
    "aperture_offset",
    "clipping_range",
    "focus_distance",
    "f_stop",
    "exposure",
    "orthographic_size",
    "film_fit",
    "gate_fit",
)


class CameraValidationError(ValidationError):
    """Camera Common payloadの検証失敗。"""


def _require_object(value: object, field_name: str) -> Mapping[str, Any]:
    """JSON objectだけを受け入れる。"""

    if not isinstance(value, Mapping):
        raise CameraValidationError(f"{field_name} must be a JSON object")
    return value


def _freeze_json(value: object, field_name: str) -> object:
    """JSON値を再帰的に検証し、変更不能な値へコピーする。"""

    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise CameraValidationError(f"{field_name} must contain valid UTF-8 strings") from exc
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CameraValidationError(f"{field_name} must contain finite numbers")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CameraValidationError(f"{field_name} object keys must be strings")
            try:
                key.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise CameraValidationError(f"{field_name} object keys must contain valid UTF-8 strings") from exc
            frozen[key] = _freeze_json(item, f"{field_name}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item, f"{field_name}[{index}]") for index, item in enumerate(value))
    raise CameraValidationError(f"{field_name} must contain JSON-compatible values")


def _thaw_json(value: object) -> object:
    """変更不能なJSON値をencode用の新しいdict/listへ戻す。"""

    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _number(value: object, field_name: str, *, positive: bool = False) -> float:
    """boolを除く有限数を正規化する。"""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CameraValidationError(f"{field_name} must be a number")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise CameraValidationError(f"{field_name} must be a finite number") from exc
    if not math.isfinite(result):
        raise CameraValidationError(f"{field_name} must be a finite number")
    if positive and result <= 0:
        raise CameraValidationError(f"{field_name} must be positive")
    return result


def _optional_number(value: object, field_name: str, *, positive: bool = False) -> float | None:
    """nullまたは有限数を正規化する。"""

    if value is None:
        return None
    return _number(value, field_name, positive=positive)


def _vector(value: object, field_name: str, *, required: bool) -> tuple[float, float] | None:
    """2要素の有限数配列を検証する。"""

    if value is None:
        if required:
            raise CameraValidationError(f"{field_name} is required for perspective projection")
        return None
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise CameraValidationError(f"{field_name} must be a two-element array")
    return tuple(_number(item, f"{field_name}[{index}]") for index, item in enumerate(value))


def _clipping_range(value: object) -> tuple[float, float]:
    """正のnear/farを検証する。"""

    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise CameraValidationError("clipping_range must be a two-element array")
    near = _number(value[0], "clipping_range[0]", positive=True)
    far = _number(value[1], "clipping_range[1]", positive=True)
    if near >= far:
        raise CameraValidationError("clipping_range near must be less than far")
    return near, far


def _optional_enum(value: object, allowed: frozenset[str], field_name: str) -> str | None:
    """nullまたは定義済みenumだけを受け入れる。"""

    if value is None:
        return None
    if not isinstance(value, str) or value not in allowed:
        raise CameraValidationError(f"unsupported {field_name}: {value!r}")
    return value


@dataclass(frozen=True)
class Camera:
    """DCC非依存なCamera Common v1 payload。

    `entity_ref`、`transform`、`time`は将来のCommon型を先取りせず、JSON objectとして保持する。
    構築時に再帰コピーするため、元入力やencode結果の変更でCameraは変化しない。
    """

    entity_ref: Mapping[str, Any]
    transform: Mapping[str, Any]
    time: Mapping[str, Any]
    projection: str
    focal_length: float | None
    horizontal_aperture: float | None
    vertical_aperture: float | None
    aperture_offset: tuple[float, float] | None
    clipping_range: tuple[float, float]
    focus_distance: float | None
    f_stop: float | None
    exposure: float | None
    orthographic_size: float | None
    film_fit: str | None
    gate_fit: str | None

    def __post_init__(self) -> None:
        """直接構築でもwire contractの不変条件を適用する。"""

        for field_name in ("entity_ref", "transform", "time"):
            value = _require_object(getattr(self, field_name), field_name)
            object.__setattr__(self, field_name, _freeze_json(value, field_name))

        if not isinstance(self.projection, str) or self.projection not in {"perspective", "orthographic"}:
            raise CameraValidationError(f"unsupported projection: {self.projection!r}")
        object.__setattr__(self, "focal_length", _optional_number(self.focal_length, "focal_length", positive=True))
        object.__setattr__(
            self,
            "horizontal_aperture",
            _optional_number(self.horizontal_aperture, "horizontal_aperture", positive=True),
        )
        object.__setattr__(
            self, "vertical_aperture", _optional_number(self.vertical_aperture, "vertical_aperture", positive=True)
        )
        object.__setattr__(
            self,
            "aperture_offset",
            _vector(self.aperture_offset, "aperture_offset", required=self.projection == "perspective"),
        )
        object.__setattr__(self, "clipping_range", _clipping_range(self.clipping_range))
        object.__setattr__(self, "focus_distance", _optional_number(self.focus_distance, "focus_distance", positive=True))
        object.__setattr__(self, "f_stop", _optional_number(self.f_stop, "f_stop", positive=True))
        object.__setattr__(self, "exposure", _optional_number(self.exposure, "exposure"))
        object.__setattr__(
            self, "orthographic_size", _optional_number(self.orthographic_size, "orthographic_size", positive=True)
        )
        object.__setattr__(self, "film_fit", _optional_enum(self.film_fit, FILM_FIT_VALUES, "film_fit"))
        object.__setattr__(self, "gate_fit", _optional_enum(self.gate_fit, GATE_FIT_VALUES, "gate_fit"))

        if self.projection == "perspective":
            for field_name in ("focal_length", "horizontal_aperture", "vertical_aperture"):
                if getattr(self, field_name) is None:
                    raise CameraValidationError(f"{field_name} is required for perspective projection")
            if self.orthographic_size is not None:
                raise CameraValidationError("orthographic_size must be null for perspective projection")
        else:
            for field_name in ("focal_length", "horizontal_aperture", "vertical_aperture", "aperture_offset"):
                if getattr(self, field_name) is not None:
                    raise CameraValidationError(f"{field_name} must be null for orthographic projection")
            if self.orthographic_size is None:
                raise CameraValidationError("orthographic_size is required for orthographic projection")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Camera":
        """JSON objectを厳密なCamera型へ変換する。"""

        data = _require_object(value, "camera")
        for key in data:
            if not isinstance(key, str):
                raise CameraValidationError("camera object keys must be strings")
            try:
                key.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise CameraValidationError("camera object keys must contain valid UTF-8 strings") from exc
        unknown = set(data) - CAMERA_FIELDS
        missing = CAMERA_FIELDS - set(data)
        if unknown or missing:
            raise CameraValidationError(f"camera has unknown or missing fields: {sorted(unknown | missing)}")
        return cls(**{field_name: data[field_name] for field_name in _CAMERA_FIELDS_IN_ORDER})

    @classmethod
    def decode(cls, payload: str | bytes | bytearray) -> "Camera":
        """UTF-8 JSONからCameraを復元する。"""

        try:
            value = json.loads(payload)
        except (TypeError, ValueError, UnicodeDecodeError) as exc:
            raise CameraValidationError(f"invalid camera JSON: {exc}") from exc
        return cls.from_dict(value)

    def to_dict(self) -> dict[str, Any]:
        """Cameraを新しいJSON-compatible dictへ変換する。"""

        return {
            "entity_ref": _thaw_json(self.entity_ref),
            "transform": _thaw_json(self.transform),
            "time": _thaw_json(self.time),
            "projection": self.projection,
            "focal_length": self.focal_length,
            "horizontal_aperture": self.horizontal_aperture,
            "vertical_aperture": self.vertical_aperture,
            "aperture_offset": _thaw_json(self.aperture_offset),
            "clipping_range": _thaw_json(self.clipping_range),
            "focus_distance": self.focus_distance,
            "f_stop": self.f_stop,
            "exposure": self.exposure,
            "orthographic_size": self.orthographic_size,
            "film_fit": self.film_fit,
            "gate_fit": self.gate_fit,
        }

    def encode(self) -> str:
        """決定的なcompact UTF-8 JSON文字列へ変換する。"""

        try:
            return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False)
        except (TypeError, ValueError, UnicodeEncodeError) as exc:
            raise CameraValidationError(f"cannot encode camera: {exc}") from exc


__all__ = (
    "CAMERA_FIELDS",
    "CAMERA_SCHEMA",
    "FILM_FIT_VALUES",
    "GATE_FIT_VALUES",
    "Camera",
    "CameraValidationError",
)
