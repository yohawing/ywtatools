"""YWTA Common Time v1のGolden JSONと境界条件を検証する。"""

from __future__ import annotations

import json
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from ywta_link import RationalRate as ExportedRationalRate
from ywta_link import Time as ExportedTime
from ywta_link import TimeValidationError as ExportedTimeValidationError
from ywta_link.time import RATE_FIELDS, TIME_FIELDS, TIME_SCHEMA, RationalRate, Time, TimeValidationError
from ywta_link.registry import DEFAULT_REGISTRY

_FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "protocol" / "ywta-link" / "v1" / "valid"


def _fixture(name: str) -> str:
    """Time Golden JSONをUTF-8文字列として読む。"""

    return (_FIXTURE_ROOT / name).read_text(encoding="utf-8")


class TimeTest(unittest.TestCase):
    """Timeのwire contractと不変条件を検証する。"""

    def test_valid_range_fixture_round_trips_without_repeated_rate(self) -> None:
        """範囲fixtureをcanonical top-level rateのまま往復する。"""

        value = Time.decode(_fixture("time-range-v1.json"))
        encoded = json.loads(value.encode())

        self.assertEqual(encoded, value.to_dict())
        self.assertEqual(set(encoded), TIME_FIELDS)
        self.assertEqual(encoded["start"], -24000)
        self.assertEqual(encoded["end_exclusive"], 24000)
        self.assertEqual(encoded["timebase"], {"rate_num": 24000, "rate_den": 1001})
        self.assertNotIn("value", encoded)
        self.assertNotIn("schema", encoded)
        self.assertEqual(DEFAULT_REGISTRY.require_schema(TIME_SCHEMA), TIME_FIELDS)
        self.assertEqual(DEFAULT_REGISTRY.require_schema(TIME_SCHEMA) & RATE_FIELDS, set())

    def test_valid_single_fixture_and_public_exports(self) -> None:
        """単一時刻fixtureとpublic exportを検証する。"""

        value = Time.decode(_fixture("time-single-v1.json"))

        self.assertEqual(value.time, 1001)
        self.assertIsNone(value.start)
        self.assertIsNone(value.end_exclusive)
        self.assertEqual(value.timebase, RationalRate(30000, 1001))
        self.assertEqual(value.sample_rate, RationalRate(24000, 1001))
        self.assertIs(ExportedTime, Time)
        self.assertIs(ExportedRationalRate, RationalRate)
        self.assertIs(ExportedTimeValidationError, TimeValidationError)

    def test_rate_is_exact_and_reduced(self) -> None:
        """29.97 fpsを近似せず保持し、非既約rateを拒否する。"""

        rate = RationalRate(30000, 1001)
        self.assertEqual(rate.rate_num, 30000)
        self.assertEqual(rate.rate_den, 1001)
        self.assertEqual(rate.to_dict(), {"rate_num": 30000, "rate_den": 1001})
        with self.assertRaises(TimeValidationError):
            RationalRate(60000, 2002)

    def test_rate_bounds_and_types_are_validated(self) -> None:
        """rateの境界、bool、浮動小数を検証する。"""

        for value in (1, 2**31 - 1):
            with self.subTest(value=value):
                self.assertEqual(RationalRate(value, 1).rate_num, value)
                self.assertEqual(RationalRate(1, value).rate_den, value)
        for numerator, denominator in ((0, 1), (-1, 1), (2**31, 1), (1, 0), (1, -1), (1, 2**31)):
            with self.subTest(numerator=numerator, denominator=denominator):
                with self.assertRaises(TimeValidationError):
                    RationalRate(numerator, denominator)
        for numerator, denominator in ((True, 1), (1, False), (1.0, 1), (1, 1.0), ("1", 1)):
            with self.subTest(numerator=numerator, denominator=denominator):
                with self.assertRaises(TimeValidationError):
                    RationalRate(numerator, denominator)

    def test_tick_json_safe_integer_bounds_and_types_are_validated(self) -> None:
        """tickのJSON safe integer境界、負値、bool、浮動小数を検証する。"""

        for tick in (-(2**53 - 1), 0, 2**53 - 1):
            value = Time(tick, None, None, RationalRate(24, 1))
            self.assertEqual(value.time, tick)
        for tick in (-(2**53), 2**53):
            with self.subTest(tick=tick):
                with self.assertRaises(TimeValidationError):
                    Time(tick, None, None, RationalRate(24, 1))
        for tick in (True, 1.0, "1"):
            with self.subTest(tick=tick):
                with self.assertRaises(TimeValidationError):
                    Time(tick, None, None, RationalRate(24, 1))

    def test_range_is_half_open_and_mode_is_exclusive(self) -> None:
        """rangeのstart < end_exclusiveとsingle/range排他を検証する。"""

        rate = RationalRate(24, 1)
        self.assertEqual(Time(None, -1, 0, rate).start, -1)
        for start, end in ((0, 0), (1, 0), (None, 1), (1, None)):
            with self.subTest(start=start, end=end):
                with self.assertRaises(TimeValidationError):
                    Time(None, start, end, rate)
        with self.assertRaises(TimeValidationError):
            Time(1, 0, 2, rate)
        with self.assertRaises(TimeValidationError):
            Time(None, None, None, rate)

    def test_mapping_rates_are_immutable_and_sample_rate_is_optional(self) -> None:
        """Mapping入力をRationalRateへ変換し、外部変更から隔離する。"""

        timebase = {"rate_num": 24, "rate_den": 1}
        sample_rate = {"rate_num": 30000, "rate_den": 1001}
        value = Time(1, None, None, timebase, sample_rate)
        timebase["rate_num"] = 48
        sample_rate["rate_num"] = 60

        self.assertIsInstance(value.timebase, RationalRate)
        self.assertIsInstance(value.sample_rate, RationalRate)
        self.assertEqual(value.timebase, RationalRate(24, 1))
        self.assertEqual(value.sample_rate, RationalRate(30000, 1001))
        self.assertIsNone(Time(1, None, None, {"rate_num": 24, "rate_den": 1}).sample_rate)
        with self.assertRaises(FrozenInstanceError):
            value.time = 2

    def test_top_level_fields_and_keys_are_strict(self) -> None:
        """unknown/missing/non-string/lone-surrogate keyを拒否する。"""

        for mutation in ("unknown", "missing", "non-string", "surrogate"):
            payload = json.loads(_fixture("time-single-v1.json"))
            if mutation == "unknown":
                payload["unexpected"] = None
            elif mutation == "missing":
                del payload["timebase"]
            elif mutation == "non-string":
                payload[1] = None
            else:
                payload["\ud800"] = None
            with self.subTest(mutation=mutation):
                with self.assertRaises(TimeValidationError):
                    Time.from_dict(payload)

    def test_nested_rate_fields_and_keys_are_strict(self) -> None:
        """nested rate objectのfield集合とUTF-8 keyを厳密に検証する。"""

        for mutation in ("unknown", "missing", "non-string", "surrogate"):
            payload = json.loads(_fixture("time-single-v1.json"))
            if mutation == "unknown":
                payload["timebase"]["extra"] = 1
            elif mutation == "missing":
                del payload["timebase"]["rate_den"]
            elif mutation == "non-string":
                payload["timebase"][1] = 1
            else:
                payload["timebase"]["\ud800"] = 1
            with self.subTest(mutation=mutation):
                with self.assertRaises(TimeValidationError):
                    Time.from_dict(payload)

        payload = json.loads(_fixture("time-single-v1.json"))
        payload["sample_rate"] = 1
        with self.assertRaises(TimeValidationError):
            Time.from_dict(payload)

    def test_invalid_json_and_utf8_are_normalized(self) -> None:
        """不正JSONと不正UTF-8を専用ValidationErrorへ変換する。"""

        with self.assertRaises(TimeValidationError):
            Time.decode(b"{not-json}")
        with self.assertRaises(TimeValidationError):
            Time.decode(b"\xff")
        with self.assertRaises(TimeValidationError):
            Time.decode("[]")

    def test_encode_is_deterministic_compact_utf8_json(self) -> None:
        """encode結果がsort keys付きcompact UTF-8 JSONになることを検証する。"""

        value = Time.decode(_fixture("time-single-v1.json"))
        encoded = value.encode()

        self.assertEqual(encoded, value.encode())
        self.assertEqual(encoded, json.dumps(value.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True))
        self.assertNotIn("\n", encoded)
        self.assertNotIn(": ", encoded)
        encoded.encode("utf-8")


if __name__ == "__main__":
    unittest.main()
