"""DCC非依存Playback Host型のcontractを検証する。"""

from dataclasses import FrozenInstanceError
import unittest

from ywta_link import (
    PlaybackHostEvent,
    PlaybackHostEventKind,
    PlaybackHostRange,
    PlaybackHostSnapshot,
    PlaybackHostValidationError,
)


def _snapshot(**changes):
    """共通Host snapshotの最小有効値を作る。"""

    value = {
        "state": "paused",
        "position": 12,
        "playback_range": PlaybackHostRange(1, 25),
        "speed": 1.0,
        "direction": "forward",
        "loop_mode": "once",
        "time_unit": "film",
        "change_id": "host-change-001",
    }
    value.update(changes)
    return PlaybackHostSnapshot(**value)


class PlaybackHostContractTests(unittest.TestCase):
    """共通Host型のimmutable性とvalidationを固定する。"""

    def test_range_and_snapshot_are_immutable_and_dcc_independent(self):
        snapshot = _snapshot()
        self.assertEqual(1, snapshot.range_start)
        self.assertEqual(25, snapshot.range_end_exclusive)
        with self.assertRaises(FrozenInstanceError):
            snapshot.position = 20

    def test_event_is_typed_and_immutable(self):
        event = PlaybackHostEvent(PlaybackHostEventKind.PAUSED_SEEK, _snapshot())
        self.assertEqual("paused_seek", event.kind)
        self.assertEqual("paused", event.snapshot.state)
        with self.assertRaises(FrozenInstanceError):
            event.kind = PlaybackHostEventKind.MODE_CHANGED
        with self.assertRaises(PlaybackHostValidationError):
            PlaybackHostEvent("paused_seek", _snapshot())
        with self.assertRaises(PlaybackHostValidationError):
            PlaybackHostEvent(PlaybackHostEventKind.PAUSED_SEEK, {})

    def test_snapshot_rejects_invalid_values(self):
        invalid_values = (
            ("state", "stopped"),
            ("position", float("nan")),
            ("speed", 0.0),
            ("speed", True),
            ("direction", "sideways"),
            ("loop_mode", "ping"),
            ("time_unit", ""),
            ("change_id", "  "),
            ("playback_range", {"start": 1, "end_exclusive": 25}),
            ("approximated_fields", ["speed"]),
        )
        for field, value in invalid_values:
            with self.subTest(field=field, value=value):
                with self.assertRaises(PlaybackHostValidationError):
                    _snapshot(**{field: value})

    def test_approximated_fields_is_explicit_and_bounded(self):
        snapshot = _snapshot(approximated_fields=("speed",))
        self.assertEqual(("speed",), snapshot.approximated_fields)
        with self.assertRaises(PlaybackHostValidationError):
            _snapshot(approximated_fields=("speed", "speed"))
        snapshot = _snapshot(approximated_fields=("loop_mode", "playback_range"))
        self.assertEqual(("loop_mode", "playback_range"), snapshot.approximated_fields)
        with self.assertRaises(PlaybackHostValidationError):
            _snapshot(approximated_fields=("unknown",))

    def test_range_requires_a_non_empty_half_open_interval(self):
        with self.assertRaises(PlaybackHostValidationError):
            PlaybackHostRange(1, 1)
        with self.assertRaises(PlaybackHostValidationError):
            PlaybackHostRange(2, 1)
