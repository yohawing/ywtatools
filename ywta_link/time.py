"""YWTA Common Time v1 の型、JSON codec、validator。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

from .errors import ValidationError, _decode_json, _encode_json
from .registry import DEFAULT_REGISTRY, SCHEMA_FIELD_ORDER

TIME_SCHEMA = "ywta.common.time.v1"
TIME_FIELDS = frozenset(DEFAULT_REGISTRY.require_schema(TIME_SCHEMA))
RATE_FIELDS = frozenset({"rate_num", "rate_den"})

_TIME_FIELDS_IN_ORDER = SCHEMA_FIELD_ORDER[TIME_SCHEMA]
_TICK_MIN = -(2**53 - 1)
_TICK_MAX = 2**53 - 1
_RATE_MIN = 1
_RATE_MAX = 2**31 - 1


class TimeValidationError(ValidationError):
    """Time Common payloadの検証失敗。"""


def _validated_object(value: object, field_name: str) -> Mapping[str, Any]:
    """JSON objectとUTF-8に変換できるkeyだけを受け入れる。"""

    if not isinstance(value, Mapping):
        raise TimeValidationError(f"{field_name} must be a JSON object")
    for key in value:
        if not isinstance(key, str):
            raise TimeValidationError(f"{field_name} object keys must be strings")
        try:
            key.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise TimeValidationError(f"{field_name} object keys must be valid UTF-8") from exc
    return value


def _integer(value: object, field_name: str, lower: int, upper: int) -> int:
    """指定範囲のboolでない整数だけを受け入れる。"""

    if isinstance(value, bool) or not isinstance(value, int):
        raise TimeValidationError(f"{field_name} must be an integer")
    if not lower <= value <= upper:
        raise TimeValidationError(f"{field_name} is outside the supported range")
    return value


def _optional_tick(value: object, field_name: str) -> int | None:
    """nullまたはJSON safe integerのtickを検証する。"""

    if value is None:
        return None
    return _integer(value, field_name, _TICK_MIN, _TICK_MAX)


def _coerce_rate(value: object, field_name: str) -> "RationalRate":
    """RationalRateまたはrate objectをimmutableなRationalRateへ変換する。"""

    if isinstance(value, RationalRate):
        return value
    if isinstance(value, Mapping):
        return RationalRate.from_dict(value, field_name=field_name)
    raise TimeValidationError(f"{field_name} must be a JSON object")


def _optional_rate(value: object, field_name: str) -> "RationalRate | None":
    """nullまたはRationalRateを検証する。"""

    if value is None:
        return None
    return _coerce_rate(value, field_name)


@dataclass(frozen=True)
class RationalRate:
    """既約な正の有理数rate。"""

    rate_num: int
    rate_den: int

    def __post_init__(self) -> None:
        """直接構築でもwire contractの不変条件を適用する。"""

        numerator = _integer(self.rate_num, "rate_num", _RATE_MIN, _RATE_MAX)
        denominator = _integer(self.rate_den, "rate_den", _RATE_MIN, _RATE_MAX)
        if math.gcd(numerator, denominator) != 1:
            raise TimeValidationError("rate_num and rate_den must be reduced")
        object.__setattr__(self, "rate_num", numerator)
        object.__setattr__(self, "rate_den", denominator)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any], *, field_name: str = "rate") -> "RationalRate":
        """JSON objectを厳密なRationalRate型へ変換する。"""

        data = _validated_object(value, field_name)
        unknown = set(data) - RATE_FIELDS
        missing = RATE_FIELDS - set(data)
        if unknown or missing:
            names = sorted(unknown | missing)
            raise TimeValidationError(f"{field_name} has unknown or missing fields: {names}")
        return cls(rate_num=data["rate_num"], rate_den=data["rate_den"])

    def to_dict(self) -> dict[str, int]:
        """RationalRateを新しいJSON objectへ変換する。"""

        return {"rate_num": self.rate_num, "rate_den": self.rate_den}


@dataclass(frozen=True)
class Time:
    """単一時刻または半開範囲を表すDCC非依存なTime Common v1 payload。"""

    time: int | None
    start: int | None
    end_exclusive: int | None
    timebase: RationalRate | Mapping[str, Any]
    sample_rate: RationalRate | Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        """直接構築でもwire contractの不変条件を適用する。"""

        object.__setattr__(self, "time", _optional_tick(self.time, "time"))
        object.__setattr__(self, "start", _optional_tick(self.start, "start"))
        object.__setattr__(self, "end_exclusive", _optional_tick(self.end_exclusive, "end_exclusive"))
        object.__setattr__(self, "timebase", _coerce_rate(self.timebase, "timebase"))
        object.__setattr__(self, "sample_rate", _optional_rate(self.sample_rate, "sample_rate"))

        if self.time is not None:
            if self.start is not None or self.end_exclusive is not None:
                raise TimeValidationError("single time cannot include range fields")
            return
        if self.start is None or self.end_exclusive is None:
            raise TimeValidationError("range requires both start and end_exclusive")
        if self.start >= self.end_exclusive:
            raise TimeValidationError("start must be less than end_exclusive")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Time":
        """JSON objectを厳密なTime型へ変換する。"""

        data = _validated_object(value, "time")
        unknown = set(data) - TIME_FIELDS
        missing = TIME_FIELDS - set(data)
        if unknown or missing:
            names = sorted(unknown | missing)
            raise TimeValidationError(f"time has unknown or missing fields: {names}")
        return cls(**{field_name: data[field_name] for field_name in _TIME_FIELDS_IN_ORDER})

    @classmethod
    def decode(cls, payload: str | bytes | bytearray) -> "Time":
        """UTF-8 JSONからTimeを復元する。"""

        return _decode_json(payload, cls.from_dict, "time", TimeValidationError)

    def to_dict(self) -> dict[str, Any]:
        """Timeを新しいJSON-compatible dictへ変換する。"""

        return {
            "time": self.time,
            "start": self.start,
            "end_exclusive": self.end_exclusive,
            "timebase": self.timebase.to_dict(),
            "sample_rate": self.sample_rate.to_dict() if self.sample_rate is not None else None,
        }

    def encode(self) -> str:
        """決定的なcompact JSON文字列へ変換する。"""

        return _encode_json(self.to_dict(), "time", TimeValidationError)


__all__ = (
    "RATE_FIELDS",
    "RationalRate",
    "TIME_FIELDS",
    "TIME_SCHEMA",
    "Time",
    "TimeValidationError",
)
