"""Playback Host時刻とwire tickのmappingを検証する。"""

from __future__ import annotations

import unittest

from ywta_link import Playback, PlaybackHostRange, PlaybackHostSnapshot, RationalRate, Time
from ywta_link.playback_mapping import (
    DEFAULT_REQUIRED_EXACT_FIELDS,
    PlaybackTimeMapper,
    PlaybackTimeMappingError,
)


def _snapshot(**overrides: object) -> PlaybackHostSnapshot:
    """テスト用のHost snapshotを作る。"""

    values: dict[str, object] = {
        "state": "playing",
        "position": 1.25,
        "playback_range": PlaybackHostRange(0.5, 3.25),
        "speed": 1.5,
        "direction": "forward",
        "loop_mode": "loop",
        "time_unit": "frames",
        "change_id": "change-001",
        "approximated_fields": (),
    }
    values.update(overrides)
    return PlaybackHostSnapshot(**values)  # type: ignore[arg-type]


class PlaybackTimeMapperTest(unittest.TestCase):
    """Playback時刻変換の境界を検証する。"""

    def test_builds_reduced_wire_timebase_from_host_rate_and_scale(self) -> None:
        """Host rateとscaleの積を既約wire timebaseへ変換する。"""

        mapper = PlaybackTimeMapper(
            ticks_per_host_unit=1001,
            host_unit_rate=RationalRate(30000, 1001),
            time_unit="frames",
        )

        self.assertEqual(mapper.wire_timebase, RationalRate(30000, 1))
        self.assertEqual(mapper.ticks_per_host_unit, 1001)
        self.assertEqual(mapper.host_unit_rate, RationalRate(30000, 1001))
        self.assertEqual(mapper.time_unit, "frames")

    def test_rate_upper_bound_fails_closed(self) -> None:
        """wire rateの分子上限超過を拒否する。"""

        maximum = 2**31 - 1
        self.assertEqual(
            PlaybackTimeMapper(
                ticks_per_host_unit=2,
                host_unit_rate=RationalRate(maximum, 2),
                time_unit="frames",
            ).wire_timebase,
            RationalRate(maximum, 1),
        )
        with self.assertRaises(PlaybackTimeMappingError):
            PlaybackTimeMapper(
                ticks_per_host_unit=2,
                host_unit_rate=RationalRate(maximum, 1),
                time_unit="frames",
            )

    def test_constructor_rejects_invalid_configuration(self) -> None:
        """scale、rate、time unit、required fieldの不正値を拒否する。"""

        for scale in (0, -1, False, 1.0, "2"):
            with self.subTest(scale=scale):
                with self.assertRaises(PlaybackTimeMappingError):
                    PlaybackTimeMapper(
                        ticks_per_host_unit=scale,  # type: ignore[arg-type]
                        host_unit_rate=RationalRate(24, 1),
                        time_unit="frames",
                    )

        for time_unit in ("", " ", None, 1):
            with self.subTest(time_unit=repr(time_unit)):
                with self.assertRaises(PlaybackTimeMappingError):
                    PlaybackTimeMapper(
                        ticks_per_host_unit=1,
                        host_unit_rate=RationalRate(24, 1),
                        time_unit=time_unit,  # type: ignore[arg-type]
                    )

        with self.assertRaises(PlaybackTimeMappingError):
            PlaybackTimeMapper(
                ticks_per_host_unit=1,
                host_unit_rate={"rate_num": 24, "rate_den": 2},
                time_unit="frames",
            )
        with self.assertRaises(PlaybackTimeMappingError):
            PlaybackTimeMapper(
                ticks_per_host_unit=1,
                host_unit_rate=RationalRate(24, 1),
                time_unit="frames",
                required_exact_fields="speed",
            )
        with self.assertRaises(PlaybackTimeMappingError):
            PlaybackTimeMapper(
                ticks_per_host_unit=1,
                host_unit_rate=RationalRate(24, 1),
                time_unit="frames",
                required_exact_fields=("unknown",),
            )
        with self.assertRaises(PlaybackTimeMappingError):
            PlaybackTimeMapper(
                ticks_per_host_unit=1,
                host_unit_rate=RationalRate(24, 1),
                time_unit="frames",
                required_exact_fields=("change_id",),
            )

    def test_host_values_are_converted_exactly_without_rounding(self) -> None:
        """scaleで整数にならないHost値を丸めずに拒否する。"""

        mapper = PlaybackTimeMapper(
            ticks_per_host_unit=4,
            host_unit_rate=RationalRate(24, 1),
            time_unit="frames",
        )
        playback = mapper.to_playback(_snapshot())

        self.assertEqual(playback.position.time, 5)
        self.assertEqual(playback.playback_range.start, 2)
        self.assertEqual(playback.playback_range.end_exclusive, 13)
        self.assertEqual(playback.position.timebase, RationalRate(96, 1))

        for field, value in (
            ("position", 0.1),
            ("playback_range", PlaybackHostRange(0.0, 1.1)),
        ):
            with self.subTest(field=field):
                source = _snapshot(**{field: value})
                with self.assertRaises(PlaybackTimeMappingError):
                    mapper.to_playback(source)

        with self.assertRaisesRegex(PlaybackTimeMappingError, "time_unit"):
            mapper.to_playback(_snapshot(time_unit="seconds"))

    def test_tick_json_safe_integer_boundaries(self) -> None:
        """JSON safe integerの両端を受理し、その外側を拒否する。"""

        maximum = 2**53 - 1
        mapper = PlaybackTimeMapper(
            ticks_per_host_unit=1,
            host_unit_rate=RationalRate(24, 1),
            time_unit="frames",
        )
        accepted = mapper.to_playback(
            _snapshot(
                position=maximum,
                playback_range=PlaybackHostRange(-maximum, maximum),
            )
        )
        self.assertEqual(maximum, accepted.position.time)
        self.assertEqual(-maximum, accepted.playback_range.start)
        for position in (2**53, -(2**53)):
            with self.subTest(position=position):
                with self.assertRaises(PlaybackTimeMappingError):
                    mapper.to_playback(_snapshot(position=position))

    def test_default_policy_requires_core_playback_fields_but_allows_speed_and_loop_approximation(self) -> None:
        """既定policyは同期の核をexactにし、speed/loop近似は明示的に許可する。"""

        mapper = PlaybackTimeMapper(
            ticks_per_host_unit=4,
            host_unit_rate=RationalRate(24, 1),
            time_unit="frames",
        )
        self.assertEqual(mapper.required_exact_fields, DEFAULT_REQUIRED_EXACT_FIELDS)

        allowed = mapper.to_playback(_snapshot(approximated_fields=("speed", "loop_mode")))
        self.assertEqual(allowed.speed, 1.5)
        self.assertEqual(allowed.loop_mode, "loop")

        for field in ("state", "position", "playback_range", "direction"):
            with self.subTest(field=field):
                with self.assertRaises(PlaybackTimeMappingError):
                    mapper.to_playback(_snapshot(approximated_fields=(field,)))

    def test_custom_policy_can_allow_all_approximated_fields(self) -> None:
        """空のrequired_exact_fieldsではHost近似を許可する。"""

        mapper = PlaybackTimeMapper(
            ticks_per_host_unit=4,
            host_unit_rate=RationalRate(24, 1),
            time_unit="frames",
            required_exact_fields=(),
        )

        self.assertEqual(mapper.to_playback(_snapshot(approximated_fields=("position", "loop_mode"))).position.time, 5)

    def test_reverse_mapping_requires_exact_wire_timebase(self) -> None:
        """逆変換はmapperと完全一致するwire timebaseだけを受け入れる。"""

        mapper = PlaybackTimeMapper(
            ticks_per_host_unit=4,
            host_unit_rate=RationalRate(24, 1),
            time_unit="frames",
        )
        playback = mapper.to_playback(_snapshot())
        result = mapper.to_host_snapshot(playback)

        self.assertEqual(result, _snapshot())
        self.assertEqual(result.approximated_fields, ())

        mismatched = Playback(
            state=playback.state,
            position=Time(playback.position.time, None, None, RationalRate(24, 1)),
            playback_range=Time(None, 2, 13, RationalRate(24, 1)),
            speed=playback.speed,
            direction=playback.direction,
            loop_mode=playback.loop_mode,
            change_id=playback.change_id,
        )
        with self.assertRaises(PlaybackTimeMappingError):
            mapper.to_host_snapshot(mismatched)

    def test_reverse_mapping_divides_ticks_by_scale(self) -> None:
        """wire tickをHost値へ戻し、近似metadataを空にする。"""

        mapper = PlaybackTimeMapper(
            ticks_per_host_unit=4,
            host_unit_rate=RationalRate(24, 1),
            time_unit="frames",
        )
        playback = Playback(
            state="paused",
            position=Time(5, None, None, mapper.wire_timebase),
            playback_range=Time(None, 2, 14, mapper.wire_timebase),
            speed=2.0,
            direction="reverse",
            loop_mode="once",
            change_id="change-002",
        )

        result = mapper.to_host_snapshot(playback)
        self.assertEqual(result.position, 1.25)
        self.assertEqual(result.playback_range, PlaybackHostRange(0.5, 3.5))
        self.assertEqual(result.time_unit, "frames")
        self.assertEqual(result.state, "paused")
        self.assertEqual(result.speed, 2.0)
        self.assertEqual(result.direction, "reverse")
        self.assertEqual(result.loop_mode, "once")
        self.assertEqual(result.change_id, "change-002")
        self.assertEqual(result.approximated_fields, ())

    def test_reverse_mapping_rejects_lossy_host_float_and_sample_rate(self) -> None:
        """逆変換で表現不能なfloatと未対応sample rateを黙って失わない。"""

        mapper = PlaybackTimeMapper(
            ticks_per_host_unit=3,
            host_unit_rate=RationalRate(24, 1),
            time_unit="frames",
        )
        lossy_tick = 2**53 - 1
        lossy = Playback(
            state="paused",
            position=Time(lossy_tick, None, None, mapper.wire_timebase),
            playback_range=Time(None, 0, 3, mapper.wire_timebase),
            speed=1.0,
            direction="forward",
            loop_mode="once",
            change_id="change-lossy",
        )
        with self.assertRaisesRegex(PlaybackTimeMappingError, "Host float"):
            mapper.to_host_snapshot(lossy)

        sample_rate = RationalRate(24, 1)
        sampled = Playback(
            state="paused",
            position=Time(3, None, None, mapper.wire_timebase, sample_rate),
            playback_range=Time(None, 0, 6, mapper.wire_timebase, sample_rate),
            speed=1.0,
            direction="forward",
            loop_mode="once",
            change_id="change-sampled",
        )
        with self.assertRaisesRegex(PlaybackTimeMappingError, "sample_rate"):
            mapper.to_host_snapshot(sampled)

    def test_mapping_rejects_non_snapshot_and_non_playback_inputs(self) -> None:
        """mapping境界で型を厳密に検証する。"""

        mapper = PlaybackTimeMapper(
            ticks_per_host_unit=1,
            host_unit_rate=RationalRate(24, 1),
            time_unit="frames",
        )
        with self.assertRaises(PlaybackTimeMappingError):
            mapper.to_playback({})  # type: ignore[arg-type]
        with self.assertRaises(PlaybackTimeMappingError):
            mapper.to_host_snapshot({})  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
