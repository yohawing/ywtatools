"""YWTA Link schema registryの公開契約を検証する。"""

from __future__ import annotations

import unittest

from ywta_link import AuthoritySnapshot, AuthoritySnapshotRequest
from ywta_link.authority import (
    AUTHORITY_SNAPSHOT_FIELDS,
    AUTHORITY_SNAPSHOT_REQUEST_FIELDS,
    AUTHORITY_SNAPSHOT_REQUEST_SCHEMA,
    AUTHORITY_SNAPSHOT_SCHEMA,
)
from ywta_link.registry import (
    DEFAULT_REGISTRY,
    SCHEMA_FIELDS,
    SchemaRegistry,
    SLOT_DESCRIPTOR_SCHEMA,
    SLOT_JOIN_SCHEMA,
    SYNC_SCHEMAS,
)


class SchemaRegistryTest(unittest.TestCase):
    """Authority snapshot schemaの登録と公開payloadを検証する。"""

    def test_authority_snapshot_schemas_have_exact_registered_fields(self) -> None:
        """Snapshotの2 schemaをexact fieldsで既定Registryへ登録する。"""

        expected = {
            AUTHORITY_SNAPSHOT_REQUEST_SCHEMA: frozenset({"session_id", "channel_id"}),
            AUTHORITY_SNAPSHOT_SCHEMA: frozenset({"session_id", "channel_id", "authority", "authority_revision"}),
        }
        for schema, fields in expected.items():
            with self.subTest(schema=schema):
                self.assertIn(schema, SYNC_SCHEMAS)
                self.assertEqual(SCHEMA_FIELDS[schema], fields)
                self.assertEqual(DEFAULT_REGISTRY.require_schema(schema), fields)

        self.assertEqual(AUTHORITY_SNAPSHOT_REQUEST_FIELDS, expected[AUTHORITY_SNAPSHOT_REQUEST_SCHEMA])
        self.assertEqual(AUTHORITY_SNAPSHOT_FIELDS, expected[AUTHORITY_SNAPSHOT_SCHEMA])

    def test_public_snapshot_payloads_round_trip_registered_fields(self) -> None:
        """公開payloadのdictがRegistryのField集合と一致する。"""

        request = AuthoritySnapshotRequest(session_id="session-001", channel_id="timeline")
        snapshot = AuthoritySnapshot(
            session_id="session-001",
            channel_id="timeline",
            authority="blender:peer-001",
            authority_revision=3,
        )

        self.assertEqual(frozenset(request.to_dict()), AUTHORITY_SNAPSHOT_REQUEST_FIELDS)
        self.assertEqual(frozenset(snapshot.to_dict()), AUTHORITY_SNAPSHOT_FIELDS)
        self.assertEqual(AuthoritySnapshotRequest.from_dict(request.to_dict()), request)
        self.assertEqual(AuthoritySnapshot.from_dict(snapshot.to_dict()), snapshot)

    def test_playback_slot_schemas_have_exact_registered_fields(self) -> None:
        expected = {
            SLOT_JOIN_SCHEMA: frozenset({"slot_id", "metadata"}),
            SLOT_DESCRIPTOR_SCHEMA: frozenset(
                {"slot_id", "session_id", "initial_authority", "metadata", "created", "state_peer"}
            ),
        }
        for schema, fields in expected.items():
            with self.subTest(schema=schema):
                self.assertEqual(DEFAULT_REGISTRY.require_schema(schema), fields)

    def test_empty_custom_registry_does_not_fall_back_to_defaults(self) -> None:
        """明示した空の登録集合を既定値と区別する。"""

        registry = SchemaRegistry({}, (), ())
        self.assertEqual(dict(registry.schemas), {})
        self.assertEqual(registry.capabilities, frozenset())
        self.assertEqual(registry.mapping_profiles, frozenset())

    def test_default_registry_collections_are_immutable(self) -> None:
        """共有する既定Registryを外部から変更できない。"""

        with self.assertRaises(TypeError):
            DEFAULT_REGISTRY.schemas["custom.v1"] = frozenset()  # type: ignore[index]
        with self.assertRaises(AttributeError):
            DEFAULT_REGISTRY.capabilities.add("custom.v1")  # type: ignore[attr-defined]
        with self.assertRaises(AttributeError):
            DEFAULT_REGISTRY.mapping_profiles.clear()  # type: ignore[attr-defined]


if __name__ == "__main__":
    unittest.main()
