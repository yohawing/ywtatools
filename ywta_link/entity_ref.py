"""YWTA Common Entity Reference v1 の型、JSON codec、validator。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from .errors import ValidationError
from .registry import DEFAULT_REGISTRY

ENTITY_REFERENCE_SCHEMA = "ywta.common.entity-ref.v1"
ENTITY_REFERENCE_FIELDS = frozenset(DEFAULT_REGISTRY.require_schema(ENTITY_REFERENCE_SCHEMA))

_ENTITY_REFERENCE_FIELDS_IN_ORDER = (
    "entity_id",
    "kind",
    "display_name",
    "namespace",
)


class EntityReferenceValidationError(ValidationError):
    """Entity Reference Common payloadの検証失敗。"""


def _valid_string(value: object, field_name: str, *, allow_null: bool = False) -> str | None:
    """空文字列、空白だけの文字列、UTF-8に変換できない文字を拒否する。"""

    if allow_null and value is None:
        return None
    if not isinstance(value, str) or not value or not value.strip():
        raise EntityReferenceValidationError(f"{field_name} must be a non-empty, non-whitespace string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise EntityReferenceValidationError(f"{field_name} must be valid UTF-8") from exc
    return value


def _validated_object(value: object) -> Mapping[str, Any]:
    """JSON objectとそのtop-level keyを検証する。"""

    if not isinstance(value, Mapping):
        raise EntityReferenceValidationError("entity reference must be a JSON object")
    for key in value:
        if not isinstance(key, str):
            raise EntityReferenceValidationError("entity reference object keys must be strings")
        try:
            key.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise EntityReferenceValidationError("entity reference object keys must be valid UTF-8") from exc
    return value


@dataclass(frozen=True)
class EntityReference:
    """DCC非依存なEntity Reference Common v1 payload。"""

    entity_id: str
    kind: str
    display_name: str
    namespace: str | None

    def __post_init__(self) -> None:
        """直接構築でもwire contractの不変条件を適用する。"""

        _valid_string(self.entity_id, "entity_id")
        _valid_string(self.kind, "kind")
        _valid_string(self.display_name, "display_name")
        _valid_string(self.namespace, "namespace", allow_null=True)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EntityReference":
        """JSON objectを厳密なEntity Reference型へ変換する。"""

        data = _validated_object(value)
        unknown = set(data) - ENTITY_REFERENCE_FIELDS
        missing = ENTITY_REFERENCE_FIELDS - set(data)
        if unknown or missing:
            raise EntityReferenceValidationError(f"entity reference has unknown or missing fields: {sorted(unknown | missing)}")
        return cls(**{field_name: data[field_name] for field_name in _ENTITY_REFERENCE_FIELDS_IN_ORDER})

    @classmethod
    def decode(cls, payload: str | bytes | bytearray) -> "EntityReference":
        """UTF-8 JSONからEntity Referenceを復元する。"""

        try:
            value = json.loads(payload)
        except (TypeError, ValueError, UnicodeDecodeError) as exc:
            raise EntityReferenceValidationError(f"invalid entity reference JSON: {exc}") from exc
        return cls.from_dict(value)

    def to_dict(self) -> dict[str, Any]:
        """Entity Referenceを新しいJSON-compatible dictへ変換する。"""

        return {
            "entity_id": self.entity_id,
            "kind": self.kind,
            "display_name": self.display_name,
            "namespace": self.namespace,
        }

    def encode(self) -> str:
        """決定的なcompact UTF-8 JSON文字列へ変換する。"""

        try:
            return json.dumps(
                self.to_dict(),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
                allow_nan=False,
            )
        except (TypeError, ValueError, UnicodeEncodeError) as exc:
            raise EntityReferenceValidationError(f"cannot encode entity reference: {exc}") from exc


__all__ = (
    "ENTITY_REFERENCE_FIELDS",
    "ENTITY_REFERENCE_SCHEMA",
    "EntityReference",
    "EntityReferenceValidationError",
)
