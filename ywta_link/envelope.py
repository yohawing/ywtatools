"""YWTA Link v1 共通Envelopeのencode/decode/validation。"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, Mapping

from .errors import EnvelopeValidationError
from .registry import is_versioned_id

MESSAGE_TYPES = frozenset(
    {
        "hello",
        "join",
        "leave",
        "subscribe",
        "unsubscribe",
        "publish",
        "request",
        "response",
        "error",
        "ping",
        "pong",
        "binary.begin",
        "binary.chunk",
        "binary.end",
    }
)
ROOM_MESSAGE_TYPES = frozenset(
    {
        "join",
        "leave",
        "subscribe",
        "unsubscribe",
        "publish",
        "request",
        "response",
        "error",
    }
)
TARGET_MESSAGE_TYPES = frozenset({"request", "response", "error"})
TOPIC_REQUIRED_TYPES = frozenset({"subscribe", "unsubscribe"})
KNOWN_FIELDS = frozenset(
    {
        "protocol_version",
        "message_id",
        "type",
        "room",
        "sender",
        "target",
        "topic",
        "correlation_id",
        "schema",
        "body",
    }
)
MAX_STRING_LENGTH = 4096
MAX_BODY_DEPTH = 32
MAX_COLLECTION_LENGTH = 1024


def _json_value(value: Any, depth: int = 0) -> bool:
    """JSONとして安全に表現できる値かを検証する。"""

    if depth > MAX_BODY_DEPTH:
        return False
    if value is None or isinstance(value, (str, bool)):
        return not isinstance(value, str) or len(value) <= MAX_STRING_LENGTH
    if isinstance(value, (int, float)):
        return not isinstance(value, float) or math.isfinite(value)
    if isinstance(value, Mapping):
        return len(value) <= MAX_COLLECTION_LENGTH and all(
            isinstance(key, str) and len(key) <= MAX_STRING_LENGTH and _json_value(item, depth + 1)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return len(value) <= MAX_COLLECTION_LENGTH and all(_json_value(item, depth + 1) for item in value)
    return False


def _required_string(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value or len(value) > MAX_STRING_LENGTH:
        raise EnvelopeValidationError(f"{field_name} must be a non-empty string")


@dataclass
class Envelope:
    """Routing情報と小さなPayloadを運ぶ共通Envelope。"""

    protocol_version: int
    message_id: str
    type: str
    sender: str
    room: str | None = None
    target: str | None = None
    topic: str | None = None
    correlation_id: str | None = None
    schema: str | None = None
    body: Any = None
    extra: dict[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> "Envelope":
        """Envelopeをfail closedで検証する。"""

        if isinstance(self.protocol_version, bool) or not isinstance(self.protocol_version, int) or self.protocol_version != 1:
            raise EnvelopeValidationError("protocol_version must be 1")
        _required_string(self.message_id, "message_id")
        _required_string(self.sender, "sender")
        if not isinstance(self.type, str) or self.type not in MESSAGE_TYPES:
            raise EnvelopeValidationError(f"unknown message type: {self.type!r}")
        if self.type in ROOM_MESSAGE_TYPES:
            _required_string(self.room, "room")
        if self.type in TARGET_MESSAGE_TYPES:
            _required_string(self.target, "target")
        if self.type in TOPIC_REQUIRED_TYPES:
            _required_string(self.topic, "topic")
        if self.type in {"response", "error"}:
            _required_string(self.correlation_id, "correlation_id")
        for field_name, value in (
            ("room", self.room),
            ("target", self.target),
            ("topic", self.topic),
            ("correlation_id", self.correlation_id),
        ):
            if value is not None:
                _required_string(value, field_name)
        if self.schema is not None:
            if not is_versioned_id(self.schema):
                raise EnvelopeValidationError(f"schema must be a versioned identifier: {self.schema!r}")
        if not _json_value(self.body):
            raise EnvelopeValidationError("body must contain JSON-compatible finite values")
        if not isinstance(self.extra, Mapping) or any(key in KNOWN_FIELDS or not isinstance(key, str) for key in self.extra):
            raise EnvelopeValidationError("extra contains a known or invalid field")
        if not _json_value(self.extra):
            raise EnvelopeValidationError("extra must contain JSON-compatible values")
        return self

    def to_dict(self) -> dict[str, Any]:
        """EnvelopeをJSON objectへ変換する。未知Fieldも保持する。"""

        self.validate()
        result: dict[str, Any] = dict(self.extra)
        result.update(
            {"protocol_version": self.protocol_version, "message_id": self.message_id, "type": self.type, "sender": self.sender}
        )
        optional = {
            "room": self.room,
            "target": self.target,
            "topic": self.topic,
            "correlation_id": self.correlation_id,
            "schema": self.schema,
            "body": self.body,
        }
        result.update({key: value for key, value in optional.items() if value is not None})
        return result

    def encode(self) -> str:
        """Envelopeを決定的なUTF-8 JSON文字列へ変換する。"""

        try:
            return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise EnvelopeValidationError(f"cannot encode envelope: {exc}") from exc

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Envelope":
        """JSON objectからEnvelopeを復元する。"""

        if not isinstance(value, Mapping):
            raise EnvelopeValidationError("envelope must be a JSON object")
        known = {key: value[key] for key in KNOWN_FIELDS if key in value}
        missing = {"protocol_version", "message_id", "type", "sender"} - known.keys()
        if missing:
            raise EnvelopeValidationError(f"missing envelope fields: {sorted(missing)}")
        known["extra"] = {key: item for key, item in value.items() if key not in KNOWN_FIELDS}
        return cls(**known)

    @classmethod
    def decode(cls, payload: str | bytes | bytearray) -> "Envelope":
        """JSON文字列またはUTF-8 bytesからEnvelopeを復元する。"""

        try:
            value = json.loads(payload)
        except (TypeError, ValueError, UnicodeDecodeError) as exc:
            raise EnvelopeValidationError(f"invalid envelope JSON: {exc}") from exc
        return cls.from_dict(value)


def encode_envelope(envelope: Envelope) -> str:
    """Envelopeの簡易encode関数。"""

    return envelope.encode()


def decode_envelope(payload: str | bytes | bytearray) -> Envelope:
    """Envelopeの簡易decode関数。"""

    return Envelope.decode(payload)
