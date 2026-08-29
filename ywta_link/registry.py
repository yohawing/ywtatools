"""YWTA Link v1 の小さなSchema/Capability registry。"""

from __future__ import annotations

import re
from types import MappingProxyType
from typing import Iterable, Mapping

from .errors import ValidationError

_VERSIONED_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*(?:\.[A-Za-z0-9_-]+)*\.v[1-9][0-9]*$")

SLOT_JOIN_SCHEMA = "ywta.session.slot.join.v1"
SLOT_DESCRIPTOR_SCHEMA = "ywta.session.slot.descriptor.v1"

SYNC_SCHEMAS = frozenset(
    {
        "ywta.sync.contract.proposed.v1",
        "ywta.sync.contract.accepted.v1",
        "ywta.sync.contract.rejected.v1",
        "ywta.sync.authority.request.v1",
        "ywta.sync.authority.accepted.v1",
        "ywta.sync.authority.rejected.v1",
        "ywta.sync.authority.snapshot.request.v1",
        "ywta.sync.authority.snapshot.v1",
        "ywta.sync.preview.v1",
        "ywta.sync.commit.v1",
        "ywta.sync.cancel.v1",
        "ywta.sync.close.v1",
    }
)

SCHEMA_FIELD_ORDER = MappingProxyType(
    {
        "ywta.common.entity-ref.v1": ("entity_id", "kind", "display_name", "namespace"),
        "ywta.common.transform.v1": (
            "entity_ref",
            "translation",
            "rotation",
            "scale",
            "coordinate_system",
            "unit",
            "rotation_order",
        ),
        "ywta.common.time.v1": ("time", "start", "end_exclusive", "timebase", "sample_rate"),
        "ywta.common.playback.v1": (
            "state",
            "position",
            "playback_range",
            "speed",
            "direction",
            "loop_mode",
            "change_id",
        ),
        "ywta.common.camera.v1": (
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
            "aspect_ratio",
            "change_id",
        ),
        "ywta.common.morph-weights.v1": (
            "entity_ref",
            "channels",
            "channel_id",
            "display_name",
            "weight",
            "neutral",
            "min",
            "max",
            "group",
            "revision",
            "change_id",
        ),
        "ywta.common.motion-clip.v1": (
            "clip_id",
            "time_range",
            "timebase",
            "channels",
            "interpolation",
            "loop_intent",
            "skeleton_binding",
            "rest_pose",
        ),
        **{key: () for key in SYNC_SCHEMAS if not key.startswith("ywta.sync.authority.")},
        "ywta.sync.authority.request.v1": (
            "session_id",
            "channel_id",
            "current_authority",
            "next_authority",
            "expected_authority_revision",
            "change_id",
        ),
        "ywta.sync.authority.accepted.v1": (
            "session_id",
            "channel_id",
            "current_authority",
            "next_authority",
            "expected_authority_revision",
            "new_authority_revision",
            "change_id",
        ),
        "ywta.sync.authority.rejected.v1": (
            "session_id",
            "channel_id",
            "current_authority",
            "next_authority",
            "expected_authority_revision",
            "change_id",
            "reason",
        ),
        "ywta.sync.authority.snapshot.request.v1": ("session_id", "channel_id"),
        "ywta.sync.authority.snapshot.v1": ("session_id", "channel_id", "authority", "authority_revision"),
        SLOT_JOIN_SCHEMA: ("slot_id", "metadata"),
        SLOT_DESCRIPTOR_SCHEMA: ("slot_id", "session_id", "initial_authority", "metadata", "created", "state_peer"),
    }
)
SCHEMA_FIELDS = MappingProxyType({schema_id: frozenset(fields) for schema_id, fields in SCHEMA_FIELD_ORDER.items()})
SCHEMA_IDS = frozenset(SCHEMA_FIELDS)

CAPABILITY_IDS = frozenset(
    {
        "entity-ref.read.v1",
        "transform.read.v1",
        "transform.apply.v1",
        "time.read.v1",
        "time.apply.v1",
        "camera.read.v1",
        "camera.apply.v1",
        "playback.read.v1",
        "playback.apply.v1",
        "morph-weights.read.v1",
        "morph-weights.apply.v1",
        "motion.read.v1",
        "motion.apply.v1",
        "sync.contract.v1",
        "sync.authority.v1",
        "sync.preview.v1",
        "sync.commit.v1",
        "sync.cancel.v1",
        "sync.close.v1",
    }
)

MAPPING_PROFILE_IDS = frozenset(
    {"identity.v1", "camera-default.v1", "playback-default.v1", "morph-default.v1", "motion-default.v1"}
)


def is_versioned_id(value: object) -> bool:
    """値がYWTAのversion付きID形式かを返す。"""

    return isinstance(value, str) and bool(_VERSIONED_ID.fullmatch(value))


class SchemaRegistry:
    """Schema、Capability、Mapping Profileの登録情報を保持する。"""

    def __init__(
        self,
        schemas: Mapping[str, Iterable[str]] | None = None,
        capabilities: Iterable[str] | None = None,
        mapping_profiles: Iterable[str] | None = None,
    ) -> None:
        schema_source = SCHEMA_FIELDS if schemas is None else schemas
        capability_source = CAPABILITY_IDS if capabilities is None else capabilities
        mapping_profile_source = MAPPING_PROFILE_IDS if mapping_profiles is None else mapping_profiles
        self.schemas = MappingProxyType({key: frozenset(value) for key, value in schema_source.items()})
        self.capabilities = frozenset(capability_source)
        self.mapping_profiles = frozenset(mapping_profile_source)

    def has_schema(self, schema_id: object) -> bool:
        """登録済みSchemaかを返す。"""

        return isinstance(schema_id, str) and schema_id in self.schemas

    def has_capability(self, capability_id: object) -> bool:
        """登録済みCapabilityかを返す。"""

        return isinstance(capability_id, str) and capability_id in self.capabilities

    def has_mapping_profile(self, profile_id: object) -> bool:
        """登録済みMapping Profileかを返す。"""

        return isinstance(profile_id, str) and profile_id in self.mapping_profiles

    def require_schema(self, schema_id: object) -> frozenset[str]:
        """Schemaを取得し、未登録または未versionなら拒否する。"""

        if not is_versioned_id(schema_id) or not self.has_schema(schema_id):
            raise ValidationError(f"unknown or unversioned schema: {schema_id!r}")
        return self.schemas[schema_id]

    def require_mapping_profile(self, profile_id: object) -> None:
        """Mapping Profileを取得し、未登録または未versionなら拒否する。"""

        if not is_versioned_id(profile_id) or not self.has_mapping_profile(profile_id):
            raise ValidationError(f"unknown or unversioned mapping profile: {profile_id!r}")

    def require_capability(self, capability_id: object) -> None:
        """Capabilityを取得し、未登録または未versionなら拒否する。"""

        if not is_versioned_id(capability_id) or not self.has_capability(capability_id):
            raise ValidationError(f"unknown or unversioned capability: {capability_id!r}")


DEFAULT_REGISTRY = SchemaRegistry()
SCHEMA_REGISTRY = DEFAULT_REGISTRY
