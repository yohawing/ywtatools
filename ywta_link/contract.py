"""短命なSync Contractの型と厳密なJSON検証。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from .errors import ContractValidationError
from .registry import DEFAULT_REGISTRY, SchemaRegistry

CLOSE_POLICIES = frozenset(
    {
        "keep-committed",
        "revert-to-baseline",
        "require-explicit-commit",
    }
)
CHANNEL_MODES = frozenset({"snapshot", "preview-commit"})
CONFLICT_POLICIES = frozenset({"single-writer"})
NEGOTIATION_STATUSES = frozenset({"exact", "approximated", "unsupported"})

_CONTRACT_FIELDS = frozenset(
    {
        "contract_version",
        "session_id",
        "room",
        "purpose",
        "owner",
        "close_policy",
        "channels",
    }
)
_CHANNEL_FIELDS = frozenset(
    {
        "channel_id",
        "schema",
        "authority",
        "targets",
        "field_subset",
        "mode",
        "conflict_policy",
        "mapping_profile",
        "required",
    }
)


def _non_empty_string(value: object, field_name: str) -> str:
    """空でない文字列だけを受け入れる。"""

    if not isinstance(value, str) or not value:
        raise ContractValidationError(f"{field_name} must be a non-empty string")
    return value


def _object(value: object, field_name: str) -> Mapping[str, Any]:
    """JSON objectだけを受け入れる。"""

    if not isinstance(value, Mapping):
        raise ContractValidationError(f"{field_name} must be a JSON object")
    return value


def _enum_string(value: object, allowed: frozenset[str], field_name: str) -> str:
    """列挙値は文字列として検証し、想定外の型も検証Errorへ変換する。"""

    if not isinstance(value, str) or value not in allowed:
        raise ContractValidationError(f"unsupported {field_name}: {value!r}")
    return value


@dataclass(frozen=True)
class SyncChannel:
    """単一Authorityで同期するContract Channel。"""

    channel_id: str
    schema: str
    authority: str
    targets: tuple[str, ...]
    field_subset: tuple[str, ...]
    mode: str
    conflict_policy: str
    mapping_profile: str
    required: bool

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
        registry: SchemaRegistry = DEFAULT_REGISTRY,
    ) -> "SyncChannel":
        """JSON objectを安全なChannel型へ変換する。"""

        data = _object(value, "channel")
        unknown = set(data) - _CHANNEL_FIELDS
        missing = _CHANNEL_FIELDS - set(data)
        if unknown or missing:
            raise ContractValidationError(f"channel has unknown or missing fields: {sorted(unknown | missing)}")

        channel_id = _non_empty_string(data["channel_id"], "channel_id")
        schema = _non_empty_string(data["schema"], "schema")
        try:
            schema_fields = registry.require_schema(schema)
            registry.require_mapping_profile(data["mapping_profile"])
        except ValueError as exc:
            raise ContractValidationError(str(exc)) from exc
        if not schema.startswith("ywta.common."):
            raise ContractValidationError("channel schema must be a registered Common schema")

        authority = _non_empty_string(data["authority"], "authority")
        targets_data = data["targets"]
        if not isinstance(targets_data, list) or not targets_data:
            raise ContractValidationError("targets must be a non-empty array")
        targets = tuple(_non_empty_string(item, "target") for item in targets_data)
        if len(set(targets)) != len(targets):
            raise ContractValidationError("targets must be unique")

        subset_data = data["field_subset"]
        if not isinstance(subset_data, list) or not subset_data:
            raise ContractValidationError("field_subset must be a non-empty array")
        field_subset = tuple(_non_empty_string(item, "field_subset item") for item in subset_data)
        if len(set(field_subset)) != len(field_subset):
            raise ContractValidationError("field_subset must be unique")
        unknown_fields = set(field_subset) - schema_fields
        if unknown_fields:
            raise ContractValidationError(f"field_subset has fields outside the schema: {sorted(unknown_fields)}")

        mode = _enum_string(data["mode"], CHANNEL_MODES, "channel mode")
        conflict_policy = _enum_string(data["conflict_policy"], CONFLICT_POLICIES, "conflict policy")
        if not isinstance(data["required"], bool):
            raise ContractValidationError("required must be a boolean")

        return cls(
            channel_id=channel_id,
            schema=schema,
            authority=authority,
            targets=targets,
            field_subset=field_subset,
            mode=mode,
            conflict_policy=conflict_policy,
            mapping_profile=data["mapping_profile"],
            required=data["required"],
        )

    def to_dict(self) -> dict[str, Any]:
        """ChannelをJSON objectへ変換する。"""

        return {
            "channel_id": self.channel_id,
            "schema": self.schema,
            "authority": self.authority,
            "targets": list(self.targets),
            "field_subset": list(self.field_subset),
            "mode": self.mode,
            "conflict_policy": self.conflict_policy,
            "mapping_profile": self.mapping_profile,
            "required": self.required,
        }


@dataclass(frozen=True)
class SyncContract:
    """Room内の短命な同期対象と終了規則。"""

    contract_version: int
    session_id: str
    room: str
    owner: str
    close_policy: str
    channels: tuple[SyncChannel, ...]
    purpose: str | None = None

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
        registry: SchemaRegistry = DEFAULT_REGISTRY,
    ) -> "SyncContract":
        """JSON objectを厳密に検証してContract型へ変換する。"""

        data = _object(value, "contract")
        unknown = set(data) - _CONTRACT_FIELDS
        required_fields = _CONTRACT_FIELDS - {"purpose"}
        missing = required_fields - set(data)
        if unknown or missing:
            raise ContractValidationError(f"contract has unknown or missing fields: {sorted(unknown | missing)}")
        if (
            isinstance(data["contract_version"], bool)
            or not isinstance(data["contract_version"], int)
            or data["contract_version"] != 1
        ):
            raise ContractValidationError("contract_version must be 1")

        channels_data = data["channels"]
        if not isinstance(channels_data, list) or not channels_data:
            raise ContractValidationError("channels must be a non-empty array")
        channels = tuple(SyncChannel.from_dict(item, registry) for item in channels_data)
        channel_ids = [channel.channel_id for channel in channels]
        if len(set(channel_ids)) != len(channel_ids):
            raise ContractValidationError("channel_id values must be unique")

        close_policy = _enum_string(data["close_policy"], CLOSE_POLICIES, "close policy")
        purpose = data.get("purpose")
        if purpose is not None:
            _non_empty_string(purpose, "purpose")
        return cls(
            contract_version=1,
            session_id=_non_empty_string(data["session_id"], "session_id"),
            room=_non_empty_string(data["room"], "room"),
            owner=_non_empty_string(data["owner"], "owner"),
            close_policy=close_policy,
            channels=channels,
            purpose=purpose,
        )

    @classmethod
    def decode(
        cls,
        payload: str | bytes | bytearray,
        registry: SchemaRegistry = DEFAULT_REGISTRY,
    ) -> "SyncContract":
        """UTF-8 JSONからContractを復元する。"""

        try:
            value = json.loads(payload)
        except (TypeError, ValueError, UnicodeDecodeError) as exc:
            raise ContractValidationError(f"invalid contract JSON: {exc}") from exc
        return cls.from_dict(value, registry)

    def to_dict(self) -> dict[str, Any]:
        """ContractをJSON objectへ変換する。"""

        result = {
            "contract_version": self.contract_version,
            "session_id": self.session_id,
            "room": self.room,
            "owner": self.owner,
            "close_policy": self.close_policy,
            "channels": [channel.to_dict() for channel in self.channels],
        }
        if self.purpose is not None:
            result["purpose"] = self.purpose
        return result

    def encode(self) -> str:
        """決定的なUTF-8 JSON文字列へ変換する。"""

        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True)


@dataclass(frozen=True)
class NegotiationResult:
    """Targetが返すChannelごとのBinding判定。"""

    channel_id: str
    status: str
    reason: str | None = None

    def __post_init__(self) -> None:
        """許可済み判定値だけを受け入れる。"""

        _non_empty_string(self.channel_id, "channel_id")
        if self.status not in NEGOTIATION_STATUSES:
            raise ContractValidationError(f"unsupported negotiation status: {self.status!r}")
        if self.reason is not None:
            _non_empty_string(self.reason, "reason")
