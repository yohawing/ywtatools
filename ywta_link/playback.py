"""YWTA Common Playback v1 の型、JSON codec、validator。"""

from __future__ import annotations

import json
import math
from collections import deque
from dataclasses import dataclass
from typing import Any, Mapping

from .errors import ValidationError
from .registry import DEFAULT_REGISTRY
from .time import Time

PLAYBACK_SCHEMA = "ywta.common.playback.v1"
PLAYBACK_FIELDS = frozenset(DEFAULT_REGISTRY.require_schema(PLAYBACK_SCHEMA))
PLAYBACK_STATE_VALUES = frozenset({"playing", "paused"})
PLAYBACK_DIRECTION_VALUES = frozenset({"forward", "reverse"})
PLAYBACK_LOOP_MODE_VALUES = frozenset({"once", "loop", "ping-pong"})

_PLAYBACK_FIELDS_IN_ORDER = (
    "state",
    "position",
    "playback_range",
    "speed",
    "direction",
    "loop_mode",
    "change_id",
)


class PlaybackValidationError(ValidationError):
    """Playback Common payloadの検証失敗。"""


def _object(value: object, field_name: str) -> Mapping[str, Any]:
    """JSON objectとUTF-8へ変換できるkeyだけを受け入れる。"""

    if not isinstance(value, Mapping):
        raise PlaybackValidationError(f"{field_name} must be a JSON object")
    for key in value:
        if not isinstance(key, str):
            raise PlaybackValidationError(f"{field_name} object keys must be strings")
        try:
            key.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise PlaybackValidationError(f"{field_name} object keys must be valid UTF-8") from exc
    return value


def _time(value: object, field_name: str) -> Time:
    """TimeまたはJSON objectをimmutableなTimeへ変換する。"""

    if isinstance(value, Time):
        return value
    try:
        data = _object(value, field_name)
        return Time.from_dict(data)
    except ValidationError as exc:
        raise PlaybackValidationError(f"invalid {field_name}: {exc}") from exc


def _enum(value: object, allowed: frozenset[str], field_name: str) -> str:
    """定義済みenumだけを受け入れる。"""

    if not isinstance(value, str) or value not in allowed:
        raise PlaybackValidationError(f"unsupported {field_name}: {value!r}")
    return value


def _speed(value: object) -> float:
    """boolでない有限の正数を再生倍率として受け入れる。"""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PlaybackValidationError("speed must be a number")
    try:
        speed = float(value)
    except (OverflowError, ValueError) as exc:
        raise PlaybackValidationError("speed must be a finite positive number") from exc
    if not math.isfinite(speed) or speed <= 0:
        raise PlaybackValidationError("speed must be a finite positive number")
    return speed


def _non_whitespace_utf8(value: object, field_name: str) -> str:
    """空白だけでないUTF-8文字列を識別子として受け入れる。"""

    if not isinstance(value, str) or not value or not value.strip():
        raise PlaybackValidationError(f"{field_name} must be a non-whitespace string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise PlaybackValidationError(f"{field_name} must be valid UTF-8") from exc
    return value


def _change_id(value: object) -> str:
    """空白だけでないUTF-8文字列をlogical change IDとして受け入れる。"""

    return _non_whitespace_utf8(value, "change_id")


class PlaybackEchoGuard:
    """単一Sync Sessionのremote changeを有界に記憶し、echo再publishを抑止する。"""

    def __init__(self, capacity: int = 256) -> None:
        """正の容量で有界FIFOを初期化する。"""

        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity <= 0:
            raise PlaybackValidationError("capacity must be a positive integer")
        self._capacity = capacity
        self._remote_change_ids: set[tuple[str, str]] = set()
        self._remote_order: deque[tuple[str, str]] = deque()

    def remember_remote(self, origin_peer_id: str, change_id: str) -> None:
        """Remote applyのoriginとchange IDを記憶する。重複keyはFIFO順を変更しない。"""

        origin_peer_id = _non_whitespace_utf8(origin_peer_id, "origin_peer_id")
        change_id = _change_id(change_id)
        key = (origin_peer_id, change_id)
        if key in self._remote_change_ids:
            return
        if len(self._remote_order) >= self._capacity:
            evicted = self._remote_order.popleft()
            self._remote_change_ids.remove(evicted)
        self._remote_order.append(key)
        self._remote_change_ids.add(key)

    def should_publish(self, origin_peer_id: str, change_id: str) -> bool:
        """originとchange IDのkeyがremote由来でなければpublish可能と判定する。"""

        origin_peer_id = _non_whitespace_utf8(origin_peer_id, "origin_peer_id")
        change_id = _change_id(change_id)
        return (origin_peer_id, change_id) not in self._remote_change_ids


@dataclass(frozen=True)
class Playback:
    """DCC非依存な再生状態を表すPlayback Common v1 payload。

    `position`はsingle-mode、`playback_range`はrange-modeのTimeでなければならず、
    構築時にTimeをimmutable化して入力objectの変更から隔離する。
    """

    state: str
    position: Time | Mapping[str, Any]
    playback_range: Time | Mapping[str, Any]
    speed: float
    direction: str
    loop_mode: str
    change_id: str

    def __post_init__(self) -> None:
        """直接constructorでもwire contractの不変条件を適用する。"""

        state = _enum(self.state, PLAYBACK_STATE_VALUES, "state")
        position = _time(self.position, "position")
        playback_range = _time(self.playback_range, "playback_range")
        if position.time is None or position.start is not None or position.end_exclusive is not None:
            raise PlaybackValidationError("position must be a single-mode Time")
        if playback_range.time is not None or playback_range.start is None or playback_range.end_exclusive is None:
            raise PlaybackValidationError("playback_range must be a range-mode Time")
        if position.timebase != playback_range.timebase:
            raise PlaybackValidationError("position and playback_range timebase must match exactly")

        object.__setattr__(self, "state", state)
        object.__setattr__(self, "position", position)
        object.__setattr__(self, "playback_range", playback_range)
        object.__setattr__(self, "speed", _speed(self.speed))
        object.__setattr__(self, "direction", _enum(self.direction, PLAYBACK_DIRECTION_VALUES, "direction"))
        object.__setattr__(self, "loop_mode", _enum(self.loop_mode, PLAYBACK_LOOP_MODE_VALUES, "loop_mode"))
        object.__setattr__(self, "change_id", _change_id(self.change_id))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Playback":
        """JSON objectを厳密なPlayback型へ変換する。"""

        data = _object(value, "playback")
        unknown = set(data) - PLAYBACK_FIELDS
        missing = PLAYBACK_FIELDS - set(data)
        if unknown or missing:
            raise PlaybackValidationError(f"playback has unknown or missing fields: {sorted(unknown | missing)}")
        return cls(**{field_name: data[field_name] for field_name in _PLAYBACK_FIELDS_IN_ORDER})

    @classmethod
    def decode(cls, payload: str | bytes | bytearray) -> "Playback":
        """UTF-8 JSONからPlaybackを復元する。"""

        try:
            value = json.loads(payload)
        except (TypeError, ValueError, UnicodeDecodeError) as exc:
            raise PlaybackValidationError(f"invalid playback JSON: {exc}") from exc
        return cls.from_dict(value)

    def to_dict(self) -> dict[str, Any]:
        """Playbackを新しいJSON-compatible dictへ変換する。"""

        return {
            "state": self.state,
            "position": self.position.to_dict(),
            "playback_range": self.playback_range.to_dict(),
            "speed": self.speed,
            "direction": self.direction,
            "loop_mode": self.loop_mode,
            "change_id": self.change_id,
        }

    def encode(self) -> str:
        """決定的なcompact UTF-8 JSON文字列へ変換する。"""

        try:
            return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False)
        except (TypeError, ValueError, UnicodeEncodeError) as exc:
            raise PlaybackValidationError(f"cannot encode playback: {exc}") from exc


__all__ = (
    "PLAYBACK_DIRECTION_VALUES",
    "PLAYBACK_FIELDS",
    "PLAYBACK_LOOP_MODE_VALUES",
    "PLAYBACK_SCHEMA",
    "PLAYBACK_STATE_VALUES",
    "Playback",
    "PlaybackEchoGuard",
    "PlaybackValidationError",
)
