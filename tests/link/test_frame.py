"""YWTA Link固定wire frameのGolden JSON検証。"""

from __future__ import annotations

import socket
import unittest
from pathlib import Path

from ywta_link.envelope import Envelope
from ywta_link.frame import FIXED_HEADER_LENGTH, Frame, FrameError, FrameTimeout

_FIXTURE = Path(__file__).resolve().parents[2] / "protocol" / "ywta-link" / "v1" / "valid" / "frame-publish.hex"


class FrameTest(unittest.TestCase):
    """固定20 byte headerとraw bodyを検証する。"""

    def test_golden_frame_round_trips_byte_for_byte(self) -> None:
        """Rust Golden frameをdecode/encodeして完全一致させる。"""

        golden = bytes.fromhex(_FIXTURE.read_text(encoding="ascii").strip())
        frame = Frame.decode(golden)

        self.assertEqual(frame.to_bytes(), golden)
        self.assertEqual(frame.body, bytes([0, 1, 2, 255]))
        self.assertEqual(frame.envelope.sender, "blender:peer-001")

    def test_socket_round_trip_keeps_raw_binary_bytes(self) -> None:
        """socket経由でもraw bodyを変換しない。"""

        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        expected = Frame(
            Envelope(
                protocol_version=1,
                message_id="publish-001",
                type="publish",
                sender="blender:peer-001",
                room="shot-010",
            ),
            bytes([0, 1, 2, 255]),
        )

        expected.write_to(left)
        actual = Frame.read_from(right)

        self.assertEqual(actual.envelope.message_id, "publish-001")
        self.assertEqual(actual.body, expected.body)

    def test_rejects_invalid_fixed_header_and_incomplete_socket_data(self) -> None:
        """magic、version、flags、途中切断をfail closedで拒否する。"""

        golden = bytearray(bytes.fromhex(_FIXTURE.read_text(encoding="ascii").strip()))
        for index, value in ((0, ord("X")), (5, 2), (7, 1)):
            invalid = golden.copy()
            invalid[index] = value
            with self.assertRaises(FrameError):
                Frame.decode(invalid)
        with self.assertRaises(FrameError):
            Frame.decode(golden[:-1])

        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        right.settimeout(0.01)
        with self.assertRaises(FrameError):
            Frame.read_from(right)
        left.close()
        with self.assertRaises(FrameError):
            Frame.read_from(right)

    def test_timeout_marks_only_unread_fixed_header_as_reusable(self) -> None:
        """idle timeoutだけを再利用可能とし、途中frame timeoutはfail closedにする。"""

        golden = bytes.fromhex(_FIXTURE.read_text(encoding="ascii").strip())
        header_length = int.from_bytes(golden[8:12], "big")
        for payload, reusable in (
            (b"", True),
            (golden[:1], False),
            (golden[: FIXED_HEADER_LENGTH + 1], False),
            (golden[: FIXED_HEADER_LENGTH + header_length + 1], False),
        ):
            left, right = socket.socketpair()
            try:
                if payload:
                    left.sendall(payload)
                right.settimeout(0.01)
                with self.assertRaises(FrameTimeout) as raised:
                    Frame.read_from(right)
                self.assertEqual(raised.exception.connection_reusable, reusable)
            finally:
                left.close()
                right.close()


if __name__ == "__main__":
    unittest.main()
