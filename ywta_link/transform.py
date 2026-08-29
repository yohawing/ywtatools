"""YWTA Common Transform v1 の型、JSON codec、validator。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

from .entity_ref import EntityReference
from .errors import ValidationError, _decode_json, _encode_json
from .registry import DEFAULT_REGISTRY, SCHEMA_FIELD_ORDER

TRANSFORM_SCHEMA = "ywta.common.transform.v1"
TRANSFORM_FIELDS = frozenset(DEFAULT_REGISTRY.require_schema(TRANSFORM_SCHEMA))
COORDINATE_SYSTEM_FIELDS = frozenset({"space", "handedness", "up_axis", "forward_axis", "parent_entity_id"})
UNIT_VALUES = frozenset({"millimeter", "centimeter", "meter"})
SPACE_VALUES = frozenset({"world", "parent"})
HANDEDNESS_VALUES = frozenset({"right", "left"})
AXIS_VALUES = frozenset({"+x", "-x", "+y", "-y", "+z", "-z"})

_TRANSFORM_FIELDS_IN_ORDER = SCHEMA_FIELD_ORDER[TRANSFORM_SCHEMA]


class TransformValidationError(ValidationError):
    """Transform Common payloadの検証失敗。"""


def _object(value: object, field_name: str) -> Mapping[str, Any]:
    """JSON objectとUTF-8に変換できるkeyだけを受け入れる。"""

    if not isinstance(value, Mapping):
        raise TransformValidationError(f"{field_name} must be a JSON object")
    for key in value:
        if not isinstance(key, str):
            raise TransformValidationError(f"{field_name} object keys must be strings")
        try:
            key.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise TransformValidationError(f"{field_name} object keys must be valid UTF-8") from exc
    return value


def _number(value: object, field_name: str) -> float:
    """boolを除く有限数をfloatへ変換する。"""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TransformValidationError(f"{field_name} must be a number")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise TransformValidationError(f"{field_name} must be a finite number") from exc
    if not math.isfinite(result):
        raise TransformValidationError(f"{field_name} must be a finite number")
    return result


def _vector(value: object, field_name: str, length: int) -> tuple[float, ...]:
    """指定長の有限数配列をimmutableなtupleへ変換する。"""

    if not isinstance(value, (list, tuple)) or len(value) != length:
        raise TransformValidationError(f"{field_name} must be a {length}-element array")
    return tuple(_number(item, f"{field_name}[{index}]") for index, item in enumerate(value))


def _enum(value: object, allowed: frozenset[str], field_name: str) -> str:
    """定義済みの文字列enumだけを受け入れる。"""

    if not isinstance(value, str) or value not in allowed:
        raise TransformValidationError(f"unsupported {field_name}: {value!r}")
    return value


def _string(value: object, field_name: str, *, allow_null: bool = False) -> str | None:
    """空白だけでないUTF-8文字列を検証する。"""

    if allow_null and value is None:
        return None
    if not isinstance(value, str) or not value or not value.strip():
        raise TransformValidationError(f"{field_name} must be a non-empty, non-whitespace string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise TransformValidationError(f"{field_name} must be valid UTF-8") from exc
    return value


def _axis_base(axis: str) -> str:
    """符号を除いたaxis名を返す。"""

    return axis[-1]


def _coerce_entity_ref(value: object) -> EntityReference:
    """EntityReferenceまたはobjectをimmutableなEntityReferenceへ変換する。"""

    if isinstance(value, EntityReference):
        return value
    try:
        return EntityReference.from_dict(_object(value, "entity_ref"))
    except ValidationError as exc:
        raise TransformValidationError(f"invalid entity_ref: {exc}") from exc


@dataclass(frozen=True)
class CoordinateSystem:
    """Transformが基準とする座標系metadata。"""

    space: str
    handedness: str
    up_axis: str
    forward_axis: str
    parent_entity_id: str | None

    def __post_init__(self) -> None:
        """直接構築でも座標系の不変条件を適用する。"""

        space = _enum(self.space, SPACE_VALUES, "coordinate_system.space")
        handedness = _enum(self.handedness, HANDEDNESS_VALUES, "coordinate_system.handedness")
        up_axis = _enum(self.up_axis, AXIS_VALUES, "coordinate_system.up_axis")
        forward_axis = _enum(self.forward_axis, AXIS_VALUES, "coordinate_system.forward_axis")
        if _axis_base(up_axis) == _axis_base(forward_axis):
            raise TransformValidationError("coordinate_system up_axis and forward_axis must use different base axes")
        parent_entity_id = _string(
            self.parent_entity_id,
            "coordinate_system.parent_entity_id",
            allow_null=True,
        )
        if space == "world" and parent_entity_id is not None:
            raise TransformValidationError("world coordinate_system must have null parent_entity_id")
        if space == "parent" and parent_entity_id is None:
            raise TransformValidationError("parent coordinate_system requires parent_entity_id")
        object.__setattr__(self, "space", space)
        object.__setattr__(self, "handedness", handedness)
        object.__setattr__(self, "up_axis", up_axis)
        object.__setattr__(self, "forward_axis", forward_axis)
        object.__setattr__(self, "parent_entity_id", parent_entity_id)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CoordinateSystem":
        """JSON objectを厳密なCoordinateSystem型へ変換する。"""

        data = _object(value, "coordinate_system")
        unknown = set(data) - COORDINATE_SYSTEM_FIELDS
        missing = COORDINATE_SYSTEM_FIELDS - set(data)
        if unknown or missing:
            names = sorted(unknown | missing)
            raise TransformValidationError(f"coordinate_system has unknown or missing fields: {names}")
        return cls(**{field_name: data[field_name] for field_name in COORDINATE_SYSTEM_FIELDS})

    def to_dict(self) -> dict[str, Any]:
        """CoordinateSystemを新しいJSON objectへ変換する。"""

        return {
            "space": self.space,
            "handedness": self.handedness,
            "up_axis": self.up_axis,
            "forward_axis": self.forward_axis,
            "parent_entity_id": self.parent_entity_id,
        }


def _coerce_coordinate_system(value: object) -> CoordinateSystem:
    """CoordinateSystemまたはobjectをimmutableなCoordinateSystemへ変換する。"""

    if isinstance(value, CoordinateSystem):
        return value
    try:
        return CoordinateSystem.from_dict(_object(value, "coordinate_system"))
    except TransformValidationError:
        raise
    except ValidationError as exc:
        raise TransformValidationError(f"invalid coordinate_system: {exc}") from exc


@dataclass(frozen=True)
class Transform:
    """DCC非依存なTransform Common v1 payload。"""

    entity_ref: EntityReference | Mapping[str, Any]
    translation: tuple[float, float, float] | list[float]
    rotation: tuple[float, float, float, float] | list[float]
    scale: tuple[float, float, float] | list[float]
    coordinate_system: CoordinateSystem | Mapping[str, Any]
    unit: str
    rotation_order: None = None

    def __post_init__(self) -> None:
        """直接構築でもwire contractの不変条件を適用する。"""

        entity_ref = _coerce_entity_ref(self.entity_ref)
        object.__setattr__(self, "entity_ref", entity_ref)
        object.__setattr__(self, "translation", _vector(self.translation, "translation", 3))
        rotation = _vector(self.rotation, "rotation", 4)
        norm = math.hypot(*rotation)
        if abs(norm - 1.0) > 1e-6:
            raise TransformValidationError("rotation quaternion norm must be within 1e-6 of 1")
        object.__setattr__(self, "rotation", rotation)
        object.__setattr__(self, "scale", _vector(self.scale, "scale", 3))
        coordinate_system = _coerce_coordinate_system(self.coordinate_system)
        if coordinate_system.space == "parent" and coordinate_system.parent_entity_id == entity_ref.entity_id:
            raise TransformValidationError("transform entity cannot be its own parent")
        object.__setattr__(self, "coordinate_system", coordinate_system)
        object.__setattr__(self, "unit", _enum(self.unit, UNIT_VALUES, "unit"))
        if self.rotation_order is not None:
            raise TransformValidationError("rotation_order must be null in transform v1")
        object.__setattr__(self, "rotation_order", None)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Transform":
        """JSON objectを厳密なTransform型へ変換する。"""

        data = _object(value, "transform")
        unknown = set(data) - TRANSFORM_FIELDS
        missing = TRANSFORM_FIELDS - set(data)
        if unknown or missing:
            names = sorted(unknown | missing)
            raise TransformValidationError(f"transform has unknown or missing fields: {names}")
        return cls(**{field_name: data[field_name] for field_name in _TRANSFORM_FIELDS_IN_ORDER})

    @classmethod
    def decode(cls, payload: str | bytes | bytearray) -> "Transform":
        """UTF-8 JSONからTransformを復元する。"""

        return _decode_json(payload, cls.from_dict, "transform", TransformValidationError)

    def to_dict(self) -> dict[str, Any]:
        """Transformを新しいJSON-compatible dictへ変換する。"""

        return {
            "entity_ref": self.entity_ref.to_dict(),
            "translation": list(self.translation),
            "rotation": list(self.rotation),
            "scale": list(self.scale),
            "coordinate_system": self.coordinate_system.to_dict(),
            "unit": self.unit,
            "rotation_order": None,
        }

    def encode(self) -> str:
        """決定的なcompact UTF-8 JSON文字列へ変換する。"""

        return _encode_json(self.to_dict(), "transform", TransformValidationError)


__all__ = (
    "AXIS_VALUES",
    "COORDINATE_SYSTEM_FIELDS",
    "CoordinateSystem",
    "HANDEDNESS_VALUES",
    "SPACE_VALUES",
    "TRANSFORM_FIELDS",
    "TRANSFORM_SCHEMA",
    "Transform",
    "TransformValidationError",
    "UNIT_VALUES",
)
