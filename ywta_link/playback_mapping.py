"""Playback Host時刻とCommon Playback wire tickの厳密な変換。"""

from __future__ import annotations

from fractions import Fraction
from typing import Any, Iterable, Mapping

from .playback import Playback
from .playback_host import PlaybackHostRange, PlaybackHostSnapshot
from .time import RationalRate, Time


_MAX_TICK = 2**53 - 1
_MAX_RATE_COMPONENT = 2**31 - 1
_HOST_APPROXIMATED_FIELDS = frozenset({"state", "position", "playback_range", "speed", "direction", "loop_mode"})
DEFAULT_REQUIRED_EXACT_FIELDS = frozenset({"state", "position", "playback_range", "direction"})


class PlaybackTimeMappingError(ValueError):
    """Playback時刻変換の失敗。"""


class PlaybackTimeMapper:
    """Host時刻単位をCommon Playbackの整数tickへ変換する。

    `ticks_per_host_unit`はHost時刻1単位を表すwire tick数である。Host値の
    Fraction(str(value)) * scaleが整数にならない場合は、丸めずに拒否する。
    """

    def __init__(
        self,
        *,
        ticks_per_host_unit: int,
        host_unit_rate: RationalRate | Mapping[str, Any],
        time_unit: str,
        required_exact_fields: Iterable[str] | None = None,
    ) -> None:
        """変換設定を検証し、wire timebaseを構築する。"""

        if isinstance(ticks_per_host_unit, bool) or not isinstance(ticks_per_host_unit, int):
            raise PlaybackTimeMappingError("ticks_per_host_unit must be a positive integer")
        if ticks_per_host_unit <= 0:
            raise PlaybackTimeMappingError("ticks_per_host_unit must be a positive integer")

        try:
            if isinstance(host_unit_rate, RationalRate):
                rate = host_unit_rate
            elif isinstance(host_unit_rate, Mapping):
                rate = RationalRate.from_dict(host_unit_rate, field_name="host_unit_rate")
            else:
                raise TypeError("host_unit_rate must be a RationalRate")
        except (TypeError, ValueError) as exc:
            raise PlaybackTimeMappingError(f"invalid host_unit_rate: {exc}") from exc

        if not isinstance(time_unit, str) or not time_unit.strip():
            raise PlaybackTimeMappingError("time_unit must be a non-whitespace string")

        exact_fields = self._validate_required_exact_fields(required_exact_fields)
        wire_timebase = self._build_wire_timebase(rate, ticks_per_host_unit)

        self._ticks_per_host_unit = ticks_per_host_unit
        self._host_unit_rate = rate
        self._wire_timebase = wire_timebase
        self._time_unit = time_unit
        self._required_exact_fields = exact_fields

    @property
    def ticks_per_host_unit(self) -> int:
        """Host時刻1単位あたりのwire tick数を返す。"""

        return self._ticks_per_host_unit

    @property
    def host_unit_rate(self) -> RationalRate:
        """Host時刻単位のrateを返す。"""

        return self._host_unit_rate

    @property
    def wire_timebase(self) -> RationalRate:
        """変換先wire tickの既約timebaseを返す。"""

        return self._wire_timebase

    @property
    def time_unit(self) -> str:
        """逆変換時に付与するHost time unitを返す。"""

        return self._time_unit

    @property
    def required_exact_fields(self) -> frozenset[str]:
        """近似を許可しないPlayback fieldの集合を返す。"""

        return self._required_exact_fields

    def to_playback(self, snapshot: PlaybackHostSnapshot) -> Playback:
        """Host snapshotを厳密なPlaybackへ変換する。"""

        if not isinstance(snapshot, PlaybackHostSnapshot):
            raise PlaybackTimeMappingError("snapshot must be a PlaybackHostSnapshot")
        if snapshot.time_unit != self._time_unit:
            raise PlaybackTimeMappingError("snapshot time_unit does not match mapper time_unit")

        approximated = frozenset(snapshot.approximated_fields)
        rejected = sorted(approximated & self._required_exact_fields)
        if rejected:
            fields = ", ".join(rejected)
            raise PlaybackTimeMappingError(f"approximated fields require exact mapping: {fields}")

        position = self._host_value_to_tick(snapshot.position, "position")
        range_start = self._host_value_to_tick(snapshot.playback_range.start, "playback_range.start")
        range_end = self._host_value_to_tick(snapshot.playback_range.end_exclusive, "playback_range.end_exclusive")

        try:
            return Playback(
                state=snapshot.state,
                position=Time(position, None, None, self._wire_timebase),
                playback_range=Time(None, range_start, range_end, self._wire_timebase),
                speed=snapshot.speed,
                direction=snapshot.direction,
                loop_mode=snapshot.loop_mode,
                change_id=snapshot.change_id,
            )
        except (TypeError, ValueError) as exc:
            raise PlaybackTimeMappingError(f"cannot construct Playback: {exc}") from exc

    def to_host_snapshot(self, playback: Playback) -> PlaybackHostSnapshot:
        """Playbackを設定済みHost時刻単位のsnapshotへ逆変換する。"""

        if not isinstance(playback, Playback):
            raise PlaybackTimeMappingError("playback must be a Playback")
        if playback.position.timebase != self._wire_timebase:
            raise PlaybackTimeMappingError("playback timebase does not match mapper wire timebase")
        if playback.playback_range.timebase != self._wire_timebase:
            raise PlaybackTimeMappingError("playback timebase does not match mapper wire timebase")
        if playback.position.sample_rate is not None or playback.playback_range.sample_rate is not None:
            raise PlaybackTimeMappingError("sample_rate is not supported by PlaybackTimeMapper")

        if (
            playback.position.time is None
            or playback.playback_range.start is None
            or playback.playback_range.end_exclusive is None
        ):
            raise PlaybackTimeMappingError("playback contains an invalid time mode")

        try:
            return PlaybackHostSnapshot(
                state=playback.state,
                position=self._tick_to_host_value(playback.position.time),
                playback_range=PlaybackHostRange(
                    start=self._tick_to_host_value(playback.playback_range.start),
                    end_exclusive=self._tick_to_host_value(playback.playback_range.end_exclusive),
                ),
                speed=playback.speed,
                direction=playback.direction,
                loop_mode=playback.loop_mode,
                time_unit=self._time_unit,
                change_id=playback.change_id,
                approximated_fields=(),
            )
        except (TypeError, ValueError) as exc:
            raise PlaybackTimeMappingError(f"cannot construct Host snapshot: {exc}") from exc

    @staticmethod
    def _validate_required_exact_fields(fields: Iterable[str] | None) -> frozenset[str]:
        """required exact fieldの型とfield名を検証する。"""

        if fields is None:
            return DEFAULT_REQUIRED_EXACT_FIELDS
        if isinstance(fields, (str, bytes)):
            raise PlaybackTimeMappingError("required_exact_fields must be an iterable of field names")
        try:
            validated = frozenset(fields)
        except TypeError as exc:
            raise PlaybackTimeMappingError("required_exact_fields must be an iterable of field names") from exc
        if any(not isinstance(field, str) or field not in _HOST_APPROXIMATED_FIELDS for field in validated):
            raise PlaybackTimeMappingError("required_exact_fields contains an unsupported field")
        return validated

    @staticmethod
    def _build_wire_timebase(host_rate: RationalRate, scale: int) -> RationalRate:
        """Host rateとscaleを乗算し、rate上限を検証する。"""

        wire_rate = Fraction(host_rate.rate_num * scale, host_rate.rate_den)
        if wire_rate.numerator > _MAX_RATE_COMPONENT or wire_rate.denominator > _MAX_RATE_COMPONENT:
            raise PlaybackTimeMappingError("wire timebase exceeds supported rate bounds")
        try:
            return RationalRate(wire_rate.numerator, wire_rate.denominator)
        except ValueError as exc:
            raise PlaybackTimeMappingError(f"invalid wire timebase: {exc}") from exc

    def _host_value_to_tick(self, value: float | int, field_name: str) -> int:
        """Host値を丸めずに整数wire tickへ変換する。"""

        try:
            scaled = Fraction(str(value)) * self._ticks_per_host_unit
        except (TypeError, ValueError, ZeroDivisionError) as exc:
            raise PlaybackTimeMappingError(f"{field_name} is not an exact host time value") from exc
        if scaled.denominator != 1:
            raise PlaybackTimeMappingError(f"{field_name} cannot be represented as an integer wire tick")
        tick = scaled.numerator
        if not -_MAX_TICK <= tick <= _MAX_TICK:
            raise PlaybackTimeMappingError(f"{field_name} is outside the supported tick range")
        return tick

    def _tick_to_host_value(self, tick: int) -> float | int:
        """整数wire tickをHost値へ戻す。"""

        if tick % self._ticks_per_host_unit == 0:
            return tick // self._ticks_per_host_unit
        value = tick / self._ticks_per_host_unit
        if Fraction(str(value)) * self._ticks_per_host_unit != tick:
            raise PlaybackTimeMappingError("wire tick cannot be represented exactly as a Host float")
        return value


__all__ = (
    "DEFAULT_REQUIRED_EXACT_FIELDS",
    "PlaybackTimeMapper",
    "PlaybackTimeMappingError",
)
