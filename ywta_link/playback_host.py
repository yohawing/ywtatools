"""DCC非依存なPlayback Host snapshotとeventの型。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


class PlaybackHostValidationError(ValueError):
    """Playback Host型の検証失敗。"""


_PLAYBACK_FIELDS = frozenset(
    {"state", "position", "playback_range", "speed", "direction", "loop_mode"}
)


class PlaybackHostEventKind(str, Enum):
    """DCC callbackを同期対象の小さな変更種別へ分類する。"""

    PLAY_STARTED = "play_started"
    PLAY_STOPPED = "play_stopped"
    PAUSED_SEEK = "paused_seek"
    RANGE_CHANGED = "range_changed"
    SPEED_CHANGED = "speed_changed"
    MODE_CHANGED = "mode_changed"


@dataclass(frozen=True)
class PlaybackHostRange:
    """Host側の時刻値による半開Playback range。"""

    start: float | int
    end_exclusive: float | int

    def __post_init__(self) -> None:
        """rangeの順序を検証する。"""

        _finite_number(self.start, "range start")
        _finite_number(self.end_exclusive, "range end_exclusive")
        if self.start >= self.end_exclusive:
            raise PlaybackHostValidationError("range start must be less than end_exclusive")


@dataclass(frozen=True)
class PlaybackHostSnapshot:
    """DCCのPlayback stateをHost objectから分離したimmutable snapshot。"""

    state: str
    position: float | int
    playback_range: PlaybackHostRange
    speed: float
    direction: str
    loop_mode: str
    time_unit: str
    change_id: str
    approximated_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """snapshotをHost callback境界で検証する。"""

        if self.state not in ("playing", "paused"):
            raise PlaybackHostValidationError("state must be playing or paused")
        _finite_number(self.position, "position")
        if not isinstance(self.playback_range, PlaybackHostRange):
            raise PlaybackHostValidationError("playback_range must be a PlaybackHostRange")
        if not isinstance(self.speed, (int, float)) or isinstance(self.speed, bool) or not math.isfinite(self.speed):
            raise PlaybackHostValidationError("speed must be a finite number")
        if self.speed <= 0:
            raise PlaybackHostValidationError("speed must be positive")
        if self.direction not in ("forward", "reverse"):
            raise PlaybackHostValidationError("direction must be forward or reverse")
        if self.loop_mode not in ("once", "loop", "ping-pong"):
            raise PlaybackHostValidationError("loop_mode is not supported")
        if not isinstance(self.time_unit, str) or not self.time_unit:
            raise PlaybackHostValidationError("time_unit must be a non-empty string")
        if not isinstance(self.change_id, str) or not self.change_id.strip():
            raise PlaybackHostValidationError("change_id must be a non-whitespace string")
        if not isinstance(self.approximated_fields, tuple):
            raise PlaybackHostValidationError("approximated_fields must be a tuple")
        if any(field not in _PLAYBACK_FIELDS for field in self.approximated_fields):
            raise PlaybackHostValidationError("approximated_fields contains an unsupported field")
        if len(set(self.approximated_fields)) != len(self.approximated_fields):
            raise PlaybackHostValidationError("approximated_fields must not contain duplicates")

    @property
    def range_start(self) -> float | int:
        """互換用にrange開始tickを返す。"""

        return self.playback_range.start

    @property
    def range_end_exclusive(self) -> float | int:
        """互換用に半開range終端tickを返す。"""

        return self.playback_range.end_exclusive


@dataclass(frozen=True)
class PlaybackHostEvent:
    """Host callbackからControllerへ渡すimmutable event。"""

    kind: PlaybackHostEventKind
    snapshot: PlaybackHostSnapshot

    def __post_init__(self) -> None:
        """Event kindとsnapshot型を厳密に検証する。"""

        if not isinstance(self.kind, PlaybackHostEventKind):
            raise PlaybackHostValidationError("kind must be a PlaybackHostEventKind")
        if not isinstance(self.snapshot, PlaybackHostSnapshot):
            raise PlaybackHostValidationError("snapshot must be a PlaybackHostSnapshot")


def _finite_number(value: object, field_name: str) -> None:
    """boolでない有限数を検証する。"""

    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise PlaybackHostValidationError(f"{field_name} must be a finite number")


__all__ = (
    "PlaybackHostEvent",
    "PlaybackHostEventKind",
    "PlaybackHostRange",
    "PlaybackHostSnapshot",
    "PlaybackHostValidationError",
)
