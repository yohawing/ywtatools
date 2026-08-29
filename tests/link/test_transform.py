"""YWTA Common Transform v1のGolden JSONと境界条件を検証する。"""

from __future__ import annotations

import json
import math
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from ywta_link import CoordinateSystem, Transform, TransformValidationError
from ywta_link.transform import (
    AXIS_VALUES,
    COORDINATE_SYSTEM_FIELDS,
    HANDEDNESS_VALUES,
    SPACE_VALUES,
    TRANSFORM_FIELDS,
    TRANSFORM_SCHEMA,
    UNIT_VALUES,
)
from ywta_link.entity_ref import EntityReference
from ywta_link.registry import DEFAULT_REGISTRY

_FIXTURE = Path(__file__).resolve().parents[2] / "protocol" / "ywta-link" / "v1" / "valid" / "transform-v1.json"


def _fixture() -> str:
    """Transform Golden JSONをUTF-8文字列として読む。"""

    return _FIXTURE.read_text(encoding="utf-8")


class TransformTest(unittest.TestCase):
    """Transformのwire contractと不変条件を検証する。"""

    def test_valid_fixture_round_trips_without_schema_discriminator(self) -> None:
        """Golden fixtureをdecode/encodeしてもpayloadへschemaを追加しない。"""

        transform = Transform.decode(_fixture())
        encoded = json.loads(transform.encode())

        self.assertEqual(encoded, transform.to_dict())
        self.assertEqual(set(encoded), TRANSFORM_FIELDS)
        self.assertNotIn("schema", encoded)
        self.assertEqual(DEFAULT_REGISTRY.require_schema(TRANSFORM_SCHEMA), TRANSFORM_FIELDS)
        self.assertEqual(
            DEFAULT_REGISTRY.require_schema(TRANSFORM_SCHEMA),
            {
                "entity_ref",
                "translation",
                "rotation",
                "scale",
                "coordinate_system",
                "unit",
                "rotation_order",
            },
        )
        self.assertNotIn("\n", transform.encode())
        self.assertNotIn(": ", transform.encode())

    def test_public_exports_and_frozen_composed_values(self) -> None:
        """public export、nested型、frozen dataclassを検証する。"""

        transform = Transform.decode(_fixture())
        self.assertIsInstance(transform.entity_ref, EntityReference)
        self.assertIsInstance(transform.coordinate_system, CoordinateSystem)
        self.assertEqual(transform.coordinate_system.parent_entity_id, None)
        with self.assertRaises(FrozenInstanceError):
            transform.unit = "meter"  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            transform.coordinate_system.space = "parent"  # type: ignore[misc]

    def test_vectors_require_exact_lengths_finite_numbers_and_no_bool(self) -> None:
        """Translation、Rotation、Scaleの長さ、有限性、boolを検証する。"""

        for field, length in (("translation", 3), ("rotation", 4), ("scale", 3)):
            for value in ([0.0] * (length - 1), [0.0] * (length + 1), "0,0,0"):
                payload = json.loads(_fixture())
                payload[field] = value
                with self.subTest(field=field, value=value):
                    with self.assertRaises(TransformValidationError):
                        Transform.from_dict(payload)

            for value in ([True] + [0.0] * (length - 1), [math.nan] + [0.0] * (length - 1)):
                payload = json.loads(_fixture())
                payload[field] = value
                with self.subTest(field=field, value=repr(value)):
                    with self.assertRaises(TransformValidationError):
                        Transform.from_dict(payload)

    def test_quaternion_norm_boundary_is_checked_without_normalization(self) -> None:
        """quaternionはnorm境界を検証し、入力値を正規化しない。"""

        for value in ([0.0, 0.0, 0.0, 1.0 + 0.5e-6], [0.0, 0.0, 0.0, 1.0 - 0.5e-6]):
            payload = json.loads(_fixture())
            payload["rotation"] = value
            transform = Transform.from_dict(payload)
            self.assertEqual(transform.rotation, tuple(value))

        for value in ([0.0, 0.0, 0.0, 1.0 + 2e-6], [0.0, 0.0, 0.0, 0.999 + 2e-6], [0.0, 0.0, 0.0, 0.0]):
            payload = json.loads(_fixture())
            payload["rotation"] = value
            with self.subTest(value=value):
                with self.assertRaises(TransformValidationError):
                    Transform.from_dict(payload)

        payload = json.loads(_fixture())
        payload["rotation"] = [0.0, 0.0, 0.0, -1.0]
        self.assertEqual(Transform.from_dict(payload).rotation, (0.0, 0.0, 0.0, -1.0))

    def test_scale_allows_zero_and_negative_values(self) -> None:
        """Scaleはzeroおよびnegativeを表現できる。"""

        payload = json.loads(_fixture())
        payload["scale"] = [0.0, -1.0, 2.0]
        self.assertEqual(Transform.from_dict(payload).scale, (0.0, -1.0, 2.0))

    def test_unit_and_rotation_order_are_closed(self) -> None:
        """Unit enumとv1のnull固定rotation_orderを検証する。"""

        self.assertEqual(UNIT_VALUES, {"millimeter", "centimeter", "meter"})
        for unit in UNIT_VALUES:
            payload = json.loads(_fixture())
            payload["unit"] = unit
            self.assertEqual(Transform.from_dict(payload).unit, unit)

        for unit in ("", "inch", None, True):
            payload = json.loads(_fixture())
            payload["unit"] = unit
            with self.subTest(unit=unit):
                with self.assertRaises(TransformValidationError):
                    Transform.from_dict(payload)

        payload = json.loads(_fixture())
        payload["rotation_order"] = "xyz"
        with self.assertRaises(TransformValidationError):
            Transform.from_dict(payload)

    def test_coordinate_system_enums_axes_and_parent_invariants(self) -> None:
        """座標系enum、axis直交性、world/parent invariantを検証する。"""

        self.assertEqual(SPACE_VALUES, {"world", "parent"})
        self.assertEqual(HANDEDNESS_VALUES, {"right", "left"})
        self.assertEqual(AXIS_VALUES, {"+x", "-x", "+y", "-y", "+z", "-z"})
        self.assertEqual(
            COORDINATE_SYSTEM_FIELDS,
            {"space", "handedness", "up_axis", "forward_axis", "parent_entity_id"},
        )

        payload = json.loads(_fixture())
        payload["coordinate_system"].update({"space": "parent", "parent_entity_id": "root:scene"})
        coordinate_system = Transform.from_dict(payload).coordinate_system
        self.assertEqual(coordinate_system.space, "parent")
        self.assertEqual(coordinate_system.parent_entity_id, "root:scene")

        invalid_coordinates = (
            {"space": "world", "handedness": "right", "up_axis": "+y", "forward_axis": "-z", "parent_entity_id": "root"},
            {"space": "parent", "handedness": "right", "up_axis": "+y", "forward_axis": "-z", "parent_entity_id": None},
            {"space": "world", "handedness": "right", "up_axis": "+y", "forward_axis": "-y", "parent_entity_id": None},
            {"space": "world", "handedness": "right", "up_axis": "+q", "forward_axis": "-z", "parent_entity_id": None},
        )
        for coordinate_system in invalid_coordinates:
            value = json.loads(_fixture())
            value["coordinate_system"] = coordinate_system
            with self.subTest(coordinate_system=coordinate_system):
                with self.assertRaises(TransformValidationError):
                    Transform.from_dict(value)

    def test_nested_keys_are_strict_and_utf8_safe(self) -> None:
        """top-levelとcoordinate_systemのunknown/missing/key型を拒否する。"""

        mutations = ("unknown", "missing", "non-string", "surrogate")
        for mutation in mutations:
            payload = json.loads(_fixture())
            if mutation == "unknown":
                payload["coordinate_system"]["unexpected"] = None
            elif mutation == "missing":
                del payload["coordinate_system"]["parent_entity_id"]
            elif mutation == "non-string":
                payload["coordinate_system"][1] = None
            else:
                payload["coordinate_system"]["\ud800"] = None
            with self.subTest(mutation=mutation):
                with self.assertRaises(TransformValidationError):
                    Transform.from_dict(payload)

        for mutation in mutations:
            payload = json.loads(_fixture())
            if mutation == "unknown":
                payload["unexpected"] = None
            elif mutation == "missing":
                del payload["unit"]
            elif mutation == "non-string":
                payload[1] = None
            else:
                payload["\ud800"] = None
            with self.subTest(top_level_mutation=mutation):
                with self.assertRaises(TransformValidationError):
                    Transform.from_dict(payload)

    def test_parent_entity_id_requires_non_whitespace_utf8_string(self) -> None:
        """Parent座標系のparent_entity_idに有効なUTF-8文字列を要求する。"""

        for value in ("", " \t", None, 1, True, "bad\ud800"):
            payload = json.loads(_fixture())
            payload["coordinate_system"]["space"] = "parent"
            payload["coordinate_system"]["parent_entity_id"] = value
            with self.subTest(value=repr(value)):
                with self.assertRaises(TransformValidationError):
                    Transform.from_dict(payload)

        payload = json.loads(_fixture())
        payload["coordinate_system"]["space"] = "parent"
        payload["coordinate_system"]["parent_entity_id"] = "親:root"
        self.assertEqual(Transform.from_dict(payload).coordinate_system.parent_entity_id, "親:root")

        payload = json.loads(_fixture())
        payload["coordinate_system"].update({"space": "parent", "parent_entity_id": payload["entity_ref"]["entity_id"]})
        with self.assertRaises(TransformValidationError):
            Transform.from_dict(payload)

    def test_entity_reference_is_composed_and_inputs_are_isolated(self) -> None:
        """EntityReferenceをcomposeし、入力変更からモデルを隔離する。"""

        payload = json.loads(_fixture())
        transform = Transform.from_dict(payload)
        payload["entity_ref"]["entity_id"] = "changed"
        payload["translation"][0] = 99.0
        self.assertEqual(transform.entity_ref.entity_id, "camera:shot-010-main")
        self.assertEqual(transform.translation[0], 0.0)
        self.assertEqual(transform.to_dict()["entity_ref"]["entity_id"], "camera:shot-010-main")

    def test_invalid_json_and_compact_utf8_encoding(self) -> None:
        """不正JSONを専用Errorへ変換し、deterministic compact UTF-8 JSONを出力する。"""

        with self.assertRaises(TransformValidationError):
            Transform.decode(b"{not-json}")
        with self.assertRaises(TransformValidationError):
            Transform.decode(b"\xff")
        transform = Transform.decode(_fixture())
        encoded = transform.encode()
        self.assertEqual(encoded, transform.encode())
        self.assertEqual(encoded, json.dumps(transform.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True))
        self.assertNotIn("\n", encoded)
        self.assertNotIn(": ", encoded)
        encoded.encode("utf-8")


if __name__ == "__main__":
    unittest.main()
