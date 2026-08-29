"""YWTA Common Entity Reference v1のGolden JSON検証。"""

from __future__ import annotations

import json
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from ywta_link import EntityReference, EntityReferenceValidationError
from ywta_link.entity_ref import (
    ENTITY_REFERENCE_FIELDS,
    ENTITY_REFERENCE_SCHEMA,
)
from ywta_link.errors import ValidationError
from ywta_link.registry import DEFAULT_REGISTRY

_FIXTURE = Path(__file__).resolve().parents[2] / "protocol" / "ywta-link" / "v1" / "valid" / "entity-ref-v1.json"


def _fixture() -> str:
    """Entity Reference Golden JSONをUTF-8文字列として読む。"""

    return _FIXTURE.read_text(encoding="utf-8")


class EntityReferenceTest(unittest.TestCase):
    """Entity Referenceのwire contractと不変条件を検証する。"""

    def test_valid_fixture_round_trips_without_schema_discriminator(self) -> None:
        """Golden fixtureをdecode/encodeしてもpayloadへschemaを追加しない。"""

        entity = EntityReference.decode(_fixture())
        encoded = json.loads(entity.encode())

        self.assertEqual(encoded, entity.to_dict())
        self.assertEqual(set(encoded), ENTITY_REFERENCE_FIELDS)
        self.assertNotIn("schema", encoded)
        self.assertEqual(DEFAULT_REGISTRY.require_schema(ENTITY_REFERENCE_SCHEMA), ENTITY_REFERENCE_FIELDS)
        self.assertNotIn("\n", entity.encode())
        self.assertNotIn(": ", entity.encode())

    def test_public_export_registry_and_frozen_model(self) -> None:
        """公開export、registry一致、frozen dataclassを検証する。"""

        entity = EntityReference("mesh:hero", "mesh/custom", "Hero Mesh", None)
        self.assertIsInstance(entity, EntityReference)
        self.assertTrue(issubclass(EntityReferenceValidationError, ValidationError))
        with self.assertRaises(FrozenInstanceError):
            entity.kind = "camera"  # type: ignore[misc]

    def test_unknown_missing_and_non_string_keys_fail_with_dedicated_error(self) -> None:
        """未知、欠落、非文字列、lone surrogateのkeyを専用Errorへ変換する。"""

        base = json.loads(_fixture())
        for mutation in (
            lambda value: value.update({"unexpected": "value"}),
            lambda value: value.pop("kind"),
            lambda value: value.update({1: "value"}),
            lambda value: value.update({"\ud800": "value"}),
        ):
            value = dict(base)
            mutation(value)
            with self.subTest(value=value):
                with self.assertRaises(EntityReferenceValidationError):
                    EntityReference.from_dict(value)

    def test_non_string_values_empty_values_and_whitespace_fail(self) -> None:
        """各文字列Fieldの型、空値、空白だけの値を拒否する。"""

        for field in ("entity_id", "kind", "display_name", "namespace"):
            for replacement in (None, 1, True, "", " \t\n"):
                if field == "namespace" and replacement is None:
                    continue
                value = json.loads(_fixture())
                value[field] = replacement
                with self.subTest(field=field, replacement=repr(replacement)):
                    with self.assertRaises(EntityReferenceValidationError):
                        EntityReference.from_dict(value)

    def test_namespace_null_and_valid_utf8_string_are_supported(self) -> None:
        """namespaceなしと拡張kindを含むnamespaceを受け入れる。"""

        value = json.loads(_fixture())
        value["namespace"] = None
        value["kind"] = "custom:deformer"
        value["display_name"] = "Hero メッシュ"
        entity = EntityReference.from_dict(value)
        self.assertIsNone(entity.namespace)
        self.assertEqual(entity.kind, "custom:deformer")
        self.assertEqual(entity.display_name, "Hero メッシュ")

    def test_invalid_utf8_strings_and_json_fail_with_dedicated_error(self) -> None:
        """lone surrogateと不正UTF-8 JSONを専用ValidationErrorへ変換する。"""

        base = json.loads(_fixture())
        for field in ("entity_id", "kind", "display_name", "namespace"):
            value = dict(base)
            value[field] = "bad\ud800"
            with self.subTest(field=field):
                with self.assertRaises(EntityReferenceValidationError):
                    EntityReference.from_dict(value)

        with self.assertRaises(EntityReferenceValidationError):
            EntityReference.decode(b"\xff")
        with self.assertRaises(EntityReferenceValidationError):
            EntityReference.decode(b"{not-json}")

    def test_constructor_applies_same_validation_as_decoder(self) -> None:
        """直接constructorにもdecodeと同じ制約を適用する。"""

        for field in ("entity_id", "kind", "display_name"):
            values = {
                "entity_id": "mesh:hero",
                "kind": "mesh",
                "display_name": "Hero",
                "namespace": None,
            }
            values[field] = " \t"
            with self.subTest(field=field):
                with self.assertRaises(EntityReferenceValidationError):
                    EntityReference(**values)

        for namespace in ("", " \t", "bad\ud800"):
            with self.subTest(namespace=repr(namespace)):
                with self.assertRaises(EntityReferenceValidationError):
                    EntityReference("mesh:hero", "mesh", "Hero", namespace)

    def test_scalar_output_does_not_share_mutable_state(self) -> None:
        """全Fieldがscalarであり、出力dict変更がmodelへ影響しない。"""

        entity = EntityReference.decode(_fixture())
        output = entity.to_dict()
        output["entity_id"] = "changed"
        output["namespace"] = None
        self.assertEqual(entity.entity_id, "camera:shot-010-main")
        self.assertEqual(entity.namespace, "shot-010")


if __name__ == "__main__":
    unittest.main()
