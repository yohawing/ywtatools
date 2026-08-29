"""YWTA Common Playback v1のGolden JSONと境界条件を検証する。"""

from __future__ import annotations

import json
import math
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from ywta_link import Playback as ExportedPlayback
from ywta_link import PlaybackValidationError as ExportedPlaybackValidationError
from ywta_link import Time
from ywta_link.contract import SyncContract
from ywta_link.playback import (
    PLAYBACK_FIELDS,
    PLAYBACK_SCHEMA,
    Playback,
    PlaybackEchoGuard,
    PlaybackValidationError,
)
from ywta_link.registry import DEFAULT_REGISTRY

_FIXTURE = Path(__file__).resolve().parents[2] / "protocol" / "ywta-link" / "v1" / "valid" / "playback-v1.json"


def _fixture() -> str:
    """Playback Golden JSONをUTF-8文字列として読む。"""

    return _FIXTURE.read_text(encoding="utf-8")


class PlaybackTest(unittest.TestCase):
    """Playbackのwire contractと不変条件を検証する。"""

    def test_valid_fixture_round_trips_without_schema_discriminator(self) -> None:
        """Golden fixtureをdecode/encodeしてもpayloadへschemaを追加しない。"""

        playback = Playback.decode(_fixture())
        encoded = json.loads(playback.encode())

        self.assertEqual(encoded, playback.to_dict())
        self.assertEqual(set(encoded), PLAYBACK_FIELDS)
        self.assertNotIn("schema", encoded)
        self.assertEqual(DEFAULT_REGISTRY.require_schema(PLAYBACK_SCHEMA), PLAYBACK_FIELDS)
        self.assertIs(ExportedPlayback, Playback)
        self.assertIs(ExportedPlaybackValidationError, PlaybackValidationError)
        self.assertNotIn("\n", playback.encode())
        self.assertNotIn(": ", playback.encode())

    def test_time_composition_and_timebase_match_are_typed(self) -> None:
        """single/rangeのTimeをcomposeし、同一timebaseだけを受け入れる。"""

        payload = json.loads(_fixture())
        playback = Playback.from_dict(payload)
        self.assertIsInstance(playback.position, Time)
        self.assertIsInstance(playback.playback_range, Time)
        self.assertEqual(playback.position.time, 1001)
        self.assertEqual(playback.playback_range.start, 0)

        payload["playback_range"]["timebase"]["rate_num"] = 30000
        with self.assertRaises(PlaybackValidationError):
            Playback.from_dict(payload)

    def test_paused_position_may_be_outside_playback_range(self) -> None:
        """paused seek/pre-rollのため、positionがrange外でも受け入れる。"""

        payload = json.loads(_fixture())
        payload["state"] = "paused"
        payload["position"]["time"] = 99999
        playback = Playback.from_dict(payload)
        self.assertEqual(playback.position.time, 99999)

    def test_timebase_match_does_not_require_matching_sample_rate(self) -> None:
        """sample rateが異なってもtimebaseが一致すればcomposeできる。"""

        payload = json.loads(_fixture())
        payload["position"]["sample_rate"] = {"rate_num": 30000, "rate_den": 1001}
        payload["playback_range"]["sample_rate"] = {"rate_num": 24, "rate_den": 1}
        playback = Playback.from_dict(payload)
        self.assertEqual(playback.position.timebase, playback.playback_range.timebase)
        self.assertNotEqual(playback.position.sample_rate, playback.playback_range.sample_rate)

    def test_time_modes_are_strict_and_nested_errors_are_normalized(self) -> None:
        """position/rangeのmodeを固定し、Time例外をPlayback例外へ正規化する。"""

        payload = json.loads(_fixture())
        payload["position"]["time"] = None
        payload["position"]["start"] = 0
        payload["position"]["end_exclusive"] = 1
        with self.assertRaises(PlaybackValidationError):
            Playback.from_dict(payload)

        payload = json.loads(_fixture())
        payload["playback_range"]["time"] = 1
        payload["playback_range"]["start"] = None
        payload["playback_range"]["end_exclusive"] = None
        with self.assertRaises(PlaybackValidationError):
            Playback.from_dict(payload)

        payload = json.loads(_fixture())
        del payload["position"]["timebase"]
        with self.assertRaises(PlaybackValidationError):
            Playback.from_dict(payload)

    def test_state_direction_and_loop_enums_are_closed(self) -> None:
        """再生状態、方向、loop意図を定義済みenumへ限定する。"""

        for field, values in (
            ("state", ("playing", "paused")),
            ("direction", ("forward", "reverse")),
            ("loop_mode", ("once", "loop", "ping-pong")),
        ):
            for value in values:
                payload = json.loads(_fixture())
                payload[field] = value
                self.assertEqual(getattr(Playback.from_dict(payload), field), value)
            for value in ("stopped", "", None, 1, []):
                payload = json.loads(_fixture())
                payload[field] = value
                with self.subTest(field=field, value=value):
                    with self.assertRaises(PlaybackValidationError):
                        Playback.from_dict(payload)

    def test_speed_is_finite_positive_and_not_boolean(self) -> None:
        """speedのbool、zero、負数、NaN、Infinityを拒否する。"""

        for value in (True, False, 0, 0.0, -1, -0.1, math.nan, math.inf, -math.inf, "1", None):
            payload = json.loads(_fixture())
            payload["speed"] = value
            with self.subTest(value=repr(value)):
                with self.assertRaises(PlaybackValidationError):
                    Playback.from_dict(payload)

        payload = json.loads(_fixture())
        payload["speed"] = 2
        self.assertEqual(Playback.from_dict(payload).speed, 2.0)

    def test_change_id_is_non_whitespace_valid_utf8_string(self) -> None:
        """logical change IDは空白、surrogate、非文字列を拒否する。"""

        for value in ("", " ", "\t\n", None, 1, [], "\ud800"):
            payload = json.loads(_fixture())
            payload["change_id"] = value
            with self.subTest(value=repr(value)):
                with self.assertRaises(PlaybackValidationError):
                    Playback.from_dict(payload)

        payload = json.loads(_fixture())
        payload["change_id"] = "  change-002  "
        self.assertEqual(Playback.from_dict(payload).change_id, "  change-002  ")

    def test_top_level_keys_json_and_utf8_are_strict(self) -> None:
        """unknown/missing/non-string/lone-surrogate keyと不正JSONを拒否する。"""

        for mutation in ("unknown", "missing", "non-string", "surrogate"):
            payload = json.loads(_fixture())
            if mutation == "unknown":
                payload["unexpected"] = None
            elif mutation == "missing":
                del payload["change_id"]
            elif mutation == "non-string":
                payload[1] = None
            else:
                payload["\ud800"] = None
            with self.subTest(mutation=mutation):
                with self.assertRaises(PlaybackValidationError):
                    Playback.from_dict(payload)

        with self.assertRaises(PlaybackValidationError):
            Playback.decode(b"{not-json}")
        with self.assertRaises(PlaybackValidationError):
            Playback.decode(b"\xff")
        with self.assertRaises(PlaybackValidationError):
            Playback.decode("[]")

    def test_input_and_output_mutation_is_isolated_and_instance_is_frozen(self) -> None:
        """入力と出力のmutable objectを共有せず、instanceをfrozenにする。"""

        payload = json.loads(_fixture())
        playback = Playback.from_dict(payload)
        payload["position"]["time"] = 999
        payload["playback_range"]["start"] = 999
        self.assertEqual(playback.position.time, 1001)
        self.assertEqual(playback.playback_range.start, 0)

        output = playback.to_dict()
        output["position"]["time"] = 999
        output["playback_range"]["start"] = 999
        self.assertEqual(playback.position.time, 1001)
        self.assertEqual(playback.playback_range.start, 0)
        with self.assertRaises(FrozenInstanceError):
            playback.state = "paused"  # type: ignore[misc]

    def test_echo_guard_suppresses_delayed_remote_callback_and_allows_new_id(self) -> None:
        """apply解除後に遅れて発生した同一change IDのcallbackもpublishさせない。"""

        guard = PlaybackEchoGuard()
        self.assertTrue(guard.should_publish("local-peer", "local-change-001"))
        guard.remember_remote("remote-peer", "remote-change-001")
        self.assertFalse(guard.should_publish("remote-peer", "remote-change-001"))
        self.assertFalse(guard.should_publish("remote-peer", "remote-change-001"))
        self.assertTrue(guard.should_publish("remote-peer", "remote-change-002"))

    def test_echo_guard_scopes_suppression_to_origin_peer(self) -> None:
        """同じchange IDでもoriginが異なるlocal/remote操作はpublishできる。"""

        guard = PlaybackEchoGuard()
        guard.remember_remote("peer-a", "change-1")
        self.assertFalse(guard.should_publish("peer-a", "change-1"))
        self.assertTrue(guard.should_publish("peer-b", "change-1"))
        self.assertTrue(guard.should_publish("local-peer", "change-1"))

    def test_echo_guard_is_owned_by_one_sync_session(self) -> None:
        """別SessionのGuardは同じoriginとchange IDを独立に扱う。"""

        first_session = PlaybackEchoGuard()
        second_session = PlaybackEchoGuard()
        first_session.remember_remote("peer-a", "change-1")

        self.assertFalse(first_session.should_publish("peer-a", "change-1"))
        self.assertTrue(second_session.should_publish("peer-a", "change-1"))

    def test_echo_guard_is_bounded_fifo_and_duplicate_does_not_reorder(self) -> None:
        """有界FIFOを維持し、重複rememberで古いIDの退避順を変えない。"""

        guard = PlaybackEchoGuard(capacity=2)
        guard.remember_remote("peer-a", "change-a")
        guard.remember_remote("peer-a", "change-b")
        guard.remember_remote("peer-a", "change-b")
        guard.remember_remote("peer-a", "change-c")

        self.assertTrue(guard.should_publish("peer-a", "change-a"))
        self.assertFalse(guard.should_publish("peer-a", "change-b"))
        self.assertFalse(guard.should_publish("peer-a", "change-c"))

    def test_echo_guard_rejects_invalid_capacity_and_change_id(self) -> None:
        """容量とchange IDはPlaybackと同じ入力境界を持つ。"""

        for capacity in (False, 0, -1, 1.0, "2", None):
            with self.subTest(capacity=repr(capacity)):
                with self.assertRaises(PlaybackValidationError):
                    PlaybackEchoGuard(capacity=capacity)  # type: ignore[arg-type]

        guard = PlaybackEchoGuard()
        for origin_peer_id in ("", " ", "\t\n", "\ud800", None, 1):
            with self.subTest(origin_peer_id=repr(origin_peer_id)):
                with self.assertRaises(PlaybackValidationError):
                    guard.remember_remote(origin_peer_id, "change-001")  # type: ignore[arg-type]
                with self.assertRaises(PlaybackValidationError):
                    guard.should_publish(origin_peer_id, "change-001")  # type: ignore[arg-type]

        for change_id in ("", " ", "\t\n", "\ud800", None, 1):
            with self.subTest(change_id=repr(change_id)):
                with self.assertRaises(PlaybackValidationError):
                    guard.remember_remote("peer-a", change_id)  # type: ignore[arg-type]
                with self.assertRaises(PlaybackValidationError):
                    guard.should_publish("peer-a", change_id)  # type: ignore[arg-type]

    def test_sync_contract_accepts_playback_subset_and_registry_entries(self) -> None:
        """Playback schema、mapping profile、capabilityをContract registryで参照できる。"""

        contract = SyncContract.from_dict(
            {
                "contract_version": 1,
                "session_id": "session-playback-001",
                "room": "shot-010",
                "purpose": "timeline playback",
                "owner": "blender:peer-001",
                "close_policy": "keep-committed",
                "channels": [
                    {
                        "channel_id": "timeline-playback",
                        "schema": PLAYBACK_SCHEMA,
                        "authority": "blender:peer-001",
                        "targets": ["maya:peer-001", "unity:peer-001"],
                        "field_subset": ["state", "position", "playback_range", "speed", "direction", "loop_mode"],
                        "mode": "snapshot",
                        "conflict_policy": "single-writer",
                        "mapping_profile": "playback-default.v1",
                        "required": True,
                    }
                ],
            }
        )

        self.assertEqual(contract.channels[0].schema, PLAYBACK_SCHEMA)
        self.assertEqual(contract.channels[0].mapping_profile, "playback-default.v1")
        self.assertTrue(DEFAULT_REGISTRY.has_capability("playback.read.v1"))
        self.assertTrue(DEFAULT_REGISTRY.has_capability("playback.apply.v1"))
        DEFAULT_REGISTRY.require_capability("playback.read.v1")
        DEFAULT_REGISTRY.require_capability("playback.apply.v1")
        DEFAULT_REGISTRY.require_mapping_profile("playback-default.v1")


if __name__ == "__main__":
    unittest.main()
