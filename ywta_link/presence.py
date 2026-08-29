"""YWTA Link v1 Peer Presence/Capability広告の型と検証。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from .errors import ValidationError

PEER_HELLO_SCHEMA = "ywta.peer.hello.v1"
PRESENCE_MAX_STRING_LENGTH = 256
PRESENCE_MAX_PROTOCOL_VERSIONS = 16
PRESENCE_MAX_PROTOCOL_VERSION = 65535
PRESENCE_MAX_CAPABILITIES = 128
PRESENCE_MAX_CAPABILITY_LENGTH = 256

_PRESENCE_FIELDS = frozenset(
    {
        "peer_id",
        "application",
        "application_version",
        "plugin_version",
        "protocol_versions",
        "capabilities",
    }
)
_VERSIONED_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*(?:\.[A-Za-z][A-Za-z0-9_-]*)*\.v[1-9][0-9]*$")


class PresenceValidationError(ValidationError):
    """Peer Presence metadataの検証失敗。"""


@dataclass(frozen=True)
class PeerPresence:
    """Helloに含める不変なPeer ID、実装情報、Capability広告。"""

    peer_id: str
    application: str
    application_version: str
    plugin_version: str
    protocol_versions: tuple[int, ...]
    capabilities: tuple[str, ...]

    def __post_init__(self) -> None:
        """構築時にschemaの全制約を検証する。"""

        self.validate()

    def validate(self) -> "PeerPresence":
        """広告を送信可能な値として再検証する。"""

        _required_string(self.peer_id, "peer_id")
        _required_string(self.application, "application")
        _required_string(self.application_version, "application_version")
        _required_string(self.plugin_version, "plugin_version")
        if not isinstance(self.protocol_versions, tuple):
            raise PresenceValidationError("protocol_versions must be an immutable tuple")
        if not 0 < len(self.protocol_versions) <= PRESENCE_MAX_PROTOCOL_VERSIONS:
            raise PresenceValidationError("protocol_versions has an invalid length")
        if any(
            isinstance(version, bool) or not isinstance(version, int) or not 1 <= version <= PRESENCE_MAX_PROTOCOL_VERSION
            for version in self.protocol_versions
        ):
            raise PresenceValidationError(f"protocol_versions must contain integers from 1 to {PRESENCE_MAX_PROTOCOL_VERSION}")
        if self.protocol_versions != tuple(sorted(set(self.protocol_versions))):
            raise PresenceValidationError("protocol_versions must be sorted and unique")
        if 1 not in self.protocol_versions:
            raise PresenceValidationError("protocol_versions must include version 1")
        if not isinstance(self.capabilities, tuple):
            raise PresenceValidationError("capabilities must be an immutable tuple")
        if len(self.capabilities) > PRESENCE_MAX_CAPABILITIES:
            raise PresenceValidationError("capabilities has an invalid length")
        for capability in self.capabilities:
            _required_string(
                capability,
                "capability",
                max_length=PRESENCE_MAX_CAPABILITY_LENGTH,
            )
            if not _VERSIONED_ID.fullmatch(capability):
                raise PresenceValidationError("capabilities must contain non-empty versioned identifiers")
        if self.capabilities != tuple(sorted(set(self.capabilities))):
            raise PresenceValidationError("capabilities must be sorted and unique")
        return self

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PeerPresence":
        """JSON objectからPeer Presenceを復元し、未知Fieldを拒否する。"""

        if not isinstance(value, Mapping):
            raise PresenceValidationError("peer hello body must be a JSON object")
        unknown = set(value) - _PRESENCE_FIELDS
        missing = _PRESENCE_FIELDS - set(value)
        if unknown:
            raise PresenceValidationError(f"unknown peer hello fields: {sorted(unknown)}")
        if missing:
            raise PresenceValidationError(f"missing peer hello fields: {sorted(missing)}")
        protocol_versions = value["protocol_versions"]
        capabilities = value["capabilities"]
        if not isinstance(protocol_versions, list):
            raise PresenceValidationError("protocol_versions must be an array")
        if not isinstance(capabilities, list):
            raise PresenceValidationError("capabilities must be an array")
        if len(protocol_versions) > PRESENCE_MAX_PROTOCOL_VERSIONS:
            raise PresenceValidationError("protocol_versions has an invalid length")
        if len(capabilities) > PRESENCE_MAX_CAPABILITIES:
            raise PresenceValidationError("capabilities has an invalid length")
        return cls(
            peer_id=value["peer_id"],
            application=value["application"],
            application_version=value["application_version"],
            plugin_version=value["plugin_version"],
            protocol_versions=tuple(protocol_versions),
            capabilities=tuple(capabilities),
        )

    @classmethod
    def decode(cls, payload: str | bytes | bytearray) -> "PeerPresence":
        """UTF-8 JSONからPeer Presenceを復元する。"""

        try:
            value = json.loads(payload)
        except (TypeError, ValueError, UnicodeDecodeError) as exc:
            raise PresenceValidationError(f"invalid peer hello JSON: {exc}") from exc
        return cls.from_dict(value)

    def to_dict(self) -> dict[str, Any]:
        """Peer PresenceをJSON objectへ変換する。"""

        self.validate()
        return {
            "peer_id": self.peer_id,
            "application": self.application,
            "application_version": self.application_version,
            "plugin_version": self.plugin_version,
            "protocol_versions": list(self.protocol_versions),
            "capabilities": list(self.capabilities),
        }

    def encode(self) -> str:
        """決定的なUTF-8 JSON文字列へ変換する。"""

        try:
            return json.dumps(
                self.to_dict(),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise PresenceValidationError(f"cannot encode peer hello: {exc}") from exc


def _required_string(
    value: object,
    field_name: str,
    *,
    max_length: int = PRESENCE_MAX_STRING_LENGTH,
) -> None:
    """Presence内の文字列Fieldを検証する。"""

    if not isinstance(value, str) or not value or len(value) > max_length:
        raise PresenceValidationError(f"{field_name} must be a non-empty string of at most {max_length} characters")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise PresenceValidationError(f"{field_name} must be valid UTF-8") from exc
