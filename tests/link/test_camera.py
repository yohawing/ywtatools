"""YWTA Common Camera v1のGolden JSON検証。"""

from __future__ import annotations

import json
import math
import unittest
from pathlib import Path

from ywta_link import Camera as ExportedCamera
from ywta_link.camera import CAMERA_FIELDS, CAMERA_SCHEMA, Camera, CameraValidationError
from ywta_link.registry import DEFAULT_REGISTRY

_FIXTURE = Path(__file__).resolve().parents[2] / "protocol" / "ywta-link" / "v1" / "valid" / "camera-v1.json"


def _fixture() -> str:
    """Camera Golden JSONをUTF-8文字列として読む。"""

    return _FIXTURE.read_text(encoding="utf-8")


class CameraTest(unittest.TestCase):
    """Cameraのwire contractと不変条件を検証する。"""

    def test_valid_fixture_round_trips_without_schema_discriminator(self) -> None:
        """Golden fixtureをdecode/encodeしてもpayloadへschemaを追加しない。"""

        camera = Camera.decode(_fixture())
        encoded = json.loads(camera.encode())

        self.assertEqual(encoded, camera.to_dict())
        self.assertEqual(set(encoded), CAMERA_FIELDS)
        self.assertNotIn("schema", encoded)
        self.assertEqual(DEFAULT_REGISTRY.require_schema(CAMERA_SCHEMA), CAMERA_FIELDS)
        self.assertIs(ExportedCamera, Camera)
        self.assertNotIn("\n", camera.encode())
        self.assertNotIn(": ", camera.encode())

    def test_unknown_and_missing_fields_fail_closed(self) -> None:
        """top-level field集合からの逸脱を拒否する。"""

        payload = json.loads(_fixture())
        payload["unexpected"] = 1
        with self.assertRaises(CameraValidationError):
            Camera.from_dict(payload)

        payload = json.loads(_fixture())
        del payload["focal_length"]
        with self.assertRaises(CameraValidationError):
            Camera.from_dict(payload)

    def test_invalid_json_and_non_utf8_fail_with_camera_validation_error(self) -> None:
        """不正JSONと不正UTF-8を専用ValidationErrorへ変換する。"""

        with self.assertRaises(CameraValidationError):
            Camera.decode(b"{not-json}")
        with self.assertRaises(CameraValidationError):
            Camera.decode(b"\xff")

    def test_non_finite_and_boolean_numbers_are_rejected(self) -> None:
        """NaN、Infinity、boolをnumberとして受け入れない。"""

        for field, value in (("focal_length", math.nan), ("horizontal_aperture", math.inf), ("f_stop", True)):
            payload = json.loads(_fixture())
            payload[field] = value
            with self.subTest(field=field):
                with self.assertRaises(CameraValidationError):
                    Camera.from_dict(payload)

        for field in ("focus_distance", "f_stop"):
            for value in (0.0, -1.0):
                payload = json.loads(_fixture())
                payload[field] = value
                with self.subTest(field=field, value=value):
                    with self.assertRaises(CameraValidationError):
                        Camera.from_dict(payload)

    def test_vector_and_nested_json_boundaries_are_rejected(self) -> None:
        """配列境界とCommon object内の非JSON値を拒否する。"""

        for aperture_offset in ([0.0], [0.0, 0.0, 0.0], [0.0, math.nan], "0,0"):
            payload = json.loads(_fixture())
            payload["aperture_offset"] = aperture_offset
            with self.subTest(aperture_offset=aperture_offset):
                with self.assertRaises(CameraValidationError):
                    Camera.from_dict(payload)

        for invalid_nested in (math.inf, "\ud800"):
            payload = json.loads(_fixture())
            payload["entity_ref"]["invalid"] = invalid_nested
            with self.subTest(invalid_nested=repr(invalid_nested)):
                with self.assertRaises(CameraValidationError):
                    Camera.from_dict(payload)

    def test_non_string_and_invalid_utf8_top_level_keys_are_normalized(self) -> None:
        """公開from_dictも不正keyを専用ValidationErrorへ変換する。"""

        payload = json.loads(_fixture())
        payload[1] = "invalid"
        with self.assertRaises(CameraValidationError):
            Camera.from_dict(payload)

        payload = json.loads(_fixture())
        payload["\ud800"] = "invalid"
        with self.assertRaises(CameraValidationError):
            Camera.from_dict(payload)

    def test_perspective_requires_lens_fields_and_rejects_orthographic_size(self) -> None:
        """Perspectiveではlens/apertureを必須にし、orthographic sizeをnullに固定する。"""

        for field in ("focal_length", "horizontal_aperture", "vertical_aperture", "aperture_offset"):
            payload = json.loads(_fixture())
            payload[field] = None
            with self.subTest(field=field):
                with self.assertRaises(CameraValidationError):
                    Camera.from_dict(payload)

        payload = json.loads(_fixture())
        payload["orthographic_size"] = 100.0
        with self.assertRaises(CameraValidationError):
            Camera.from_dict(payload)

    def test_orthographic_requires_size_and_nulls_perspective_fields(self) -> None:
        """Orthographicではsizeを必須にし、perspective専用値をnullにする。"""

        payload = json.loads(_fixture())
        payload.update(
            {
                "projection": "orthographic",
                "focal_length": None,
                "horizontal_aperture": None,
                "vertical_aperture": None,
                "aperture_offset": None,
                "orthographic_size": 2000.0,
            }
        )
        camera = Camera.from_dict(payload)
        self.assertEqual(camera.projection, "orthographic")
        self.assertEqual(camera.orthographic_size, 2000.0)

        payload["orthographic_size"] = None
        with self.assertRaises(CameraValidationError):
            Camera.from_dict(payload)

        payload["orthographic_size"] = 2000.0
        payload["focal_length"] = 50.0
        with self.assertRaises(CameraValidationError):
            Camera.from_dict(payload)

    def test_range_and_fit_invariants_are_validated(self) -> None:
        """clip range、正数長さ、fit enumを検証する。"""

        for clipping_range in ([0.0, 100.0], [100.0, 100.0], [101.0, 100.0], [1.0, math.inf]):
            payload = json.loads(_fixture())
            payload["clipping_range"] = clipping_range
            with self.subTest(clipping_range=clipping_range):
                with self.assertRaises(CameraValidationError):
                    Camera.from_dict(payload)

        payload = json.loads(_fixture())
        payload["film_fit"] = "stretch"
        with self.assertRaises(CameraValidationError):
            Camera.from_dict(payload)

        payload["film_fit"] = None
        payload["gate_fit"] = "vertical"
        self.assertEqual(Camera.from_dict(payload).gate_fit, "vertical")

    def test_nested_objects_are_isolated_from_input_and_output_mutation(self) -> None:
        """Common objectを深くコピーし、外部mutable stateを保持しない。"""

        payload = json.loads(_fixture())
        payload["entity_ref"]["metadata"] = {"tags": ["hero"]}
        camera = Camera.from_dict(payload)
        payload["entity_ref"]["metadata"]["tags"].append("changed-input")
        self.assertEqual(camera.entity_ref["metadata"]["tags"], ("hero",))

        output = camera.to_dict()
        output["entity_ref"]["metadata"]["tags"].append("changed-output")
        self.assertEqual(camera.entity_ref["metadata"]["tags"], ("hero",))
        with self.assertRaises(TypeError):
            camera.entity_ref["metadata"] = {}


if __name__ == "__main__":
    unittest.main()
