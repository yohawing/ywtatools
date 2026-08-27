"""YWTA Link v1の固定wire frameを扱う依存なし実装。"""

from __future__ import annotations

import json
import socket
import struct
from dataclasses import dataclass, field
from typing import Any

from .envelope import Envelope
from .errors import EnvelopeValidationError

FRAME_MAGIC = b"YWTL"
FRAME_PROTOCOL_VERSION = 1
FRAME_FLAGS = 0
FIXED_HEADER_LENGTH = 20
_FIXED_HEADER = struct.Struct(">4sHHIQ")


class FrameError(ValueError):
    """固定frameのencode/decodeまたはI/O失敗。"""


@dataclass(frozen=True)
class FrameLimits:
    """frame受信時に適用する明示的なbyte上限。"""

    max_header_length: int = 64 * 1024
    max_body_length: int = 16 * 1024 * 1024


DEFAULT_FRAME_LIMITS = FrameLimits()


@dataclass
class Frame:
    """JSON Envelopeと変更しないraw binary bodyを運ぶframe。"""

    envelope: Envelope
    body: bytes = b""
    _wire_header: bytes | None = field(default=None, repr=False, compare=False)
    _decoded_header: dict[str, Any] | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Envelopeとraw bodyの型をfail closedで検証する。"""

        self.envelope.validate()
        if not isinstance(self.body, bytes):
            raise FrameError("body must be bytes")

    def to_bytes(self, limits: FrameLimits = DEFAULT_FRAME_LIMITS) -> bytes:
        """Rust実装と同一layoutのbyte列へencodeする。"""

        header = self._header_bytes()
        _validate_lengths(len(header), len(self.body), limits)
        fixed_header = _FIXED_HEADER.pack(
            FRAME_MAGIC,
            FRAME_PROTOCOL_VERSION,
            FRAME_FLAGS,
            len(header),
            len(self.body),
        )
        return fixed_header + header + self.body

    def write_to(self, destination: Any, limits: FrameLimits = DEFAULT_FRAME_LIMITS) -> None:
        """socketまたはbyte streamへframeを完全に書き込む。"""

        data = self.to_bytes(limits)
        try:
            if hasattr(destination, "sendall"):
                destination.sendall(data)
                return
            written = destination.write(data)
        except OSError as exc:
            raise FrameError(f"frame write failed: {exc}") from exc
        if written is not None and written != len(data):
            raise FrameError("frame write was truncated")

    @classmethod
    def decode(cls, data: bytes | bytearray, limits: FrameLimits = DEFAULT_FRAME_LIMITS) -> "Frame":
        """frameだけを含むbyte列をdecodeする。"""

        raw_data = bytes(data)
        if len(raw_data) < FIXED_HEADER_LENGTH:
            raise FrameError("truncated frame")
        header_length, body_length = _decode_fixed_header(raw_data[:FIXED_HEADER_LENGTH], limits)
        expected_length = FIXED_HEADER_LENGTH + header_length + body_length
        if len(raw_data) < expected_length:
            raise FrameError("truncated frame")
        if len(raw_data) > expected_length:
            raise FrameError("frame contains trailing bytes")
        header_end = FIXED_HEADER_LENGTH + header_length
        return cls._from_wire(raw_data[FIXED_HEADER_LENGTH:header_end], raw_data[header_end:])

    @classmethod
    def read_from(cls, source: Any, limits: FrameLimits = DEFAULT_FRAME_LIMITS) -> "Frame":
        """socketまたはbyte streamから正確に1個のframeを読む。"""

        fixed_header = _read_exact(source, FIXED_HEADER_LENGTH)
        header_length, body_length = _decode_fixed_header(fixed_header, limits)
        header = _read_exact(source, header_length)
        body = _read_exact(source, body_length)
        return cls._from_wire(header, body)

    @classmethod
    def _from_wire(cls, header: bytes, body: bytes) -> "Frame":
        """UTF-8 JSON headerを検証してframeを復元する。"""

        try:
            decoded_header = json.loads(header.decode("utf-8"))
            envelope = Envelope.from_dict(decoded_header)
        except (UnicodeDecodeError, json.JSONDecodeError, EnvelopeValidationError, TypeError) as exc:
            raise FrameError(f"invalid frame header: {exc}") from exc
        if not isinstance(decoded_header, dict):
            raise FrameError("frame header must be a JSON object")
        return cls(
            envelope=envelope,
            body=body,
            _wire_header=header,
            _decoded_header=decoded_header,
        )

    def _header_bytes(self) -> bytes:
        """未変更のdecode済みHeaderはwire byte列を保持する。"""

        try:
            envelope_data = self.envelope.to_dict()
        except EnvelopeValidationError as exc:
            raise FrameError(f"invalid frame envelope: {exc}") from exc
        if self._wire_header is not None and self._decoded_header == envelope_data:
            return self._wire_header
        try:
            return self.envelope.encode().encode("utf-8")
        except EnvelopeValidationError as exc:
            raise FrameError(f"invalid frame envelope: {exc}") from exc


def encode_frame(frame: Frame, limits: FrameLimits = DEFAULT_FRAME_LIMITS) -> bytes:
    """Frameの簡易encode関数。"""

    return frame.to_bytes(limits)


def decode_frame(data: bytes | bytearray, limits: FrameLimits = DEFAULT_FRAME_LIMITS) -> Frame:
    """Frameの簡易decode関数。"""

    return Frame.decode(data, limits)


def read_frame(source: Any, limits: FrameLimits = DEFAULT_FRAME_LIMITS) -> Frame:
    """Frameの簡易read関数。"""

    return Frame.read_from(source, limits)


def write_frame(frame: Frame, destination: Any, limits: FrameLimits = DEFAULT_FRAME_LIMITS) -> None:
    """Frameの簡易write関数。"""

    frame.write_to(destination, limits)


def _decode_fixed_header(fixed_header: bytes, limits: FrameLimits) -> tuple[int, int]:
    """固定20 byte headerを検証してpayload長を返す。"""

    magic, version, flags, header_length, body_length = _FIXED_HEADER.unpack(fixed_header)
    if magic != FRAME_MAGIC:
        raise FrameError("invalid frame magic")
    if version != FRAME_PROTOCOL_VERSION:
        raise FrameError(f"unsupported frame version: {version}")
    if flags != FRAME_FLAGS:
        raise FrameError(f"unsupported frame flags: {flags}")
    _validate_lengths(header_length, body_length, limits)
    return header_length, body_length


def _validate_lengths(header_length: int, body_length: int, limits: FrameLimits) -> None:
    """Headerとbodyが設定済み上限内かを検証する。"""

    if (
        not isinstance(header_length, int)
        or not isinstance(body_length, int)
        or header_length < 0
        or body_length < 0
        or header_length > limits.max_header_length
        or body_length > limits.max_body_length
    ):
        raise FrameError("frame length exceeds configured limit")


def _read_exact(source: Any, length: int) -> bytes:
    """EOF、timeout、途中切断を区別せずfail closedで読む。"""

    parts: list[bytes] = []
    remaining = length
    while remaining:
        try:
            if hasattr(source, "recv"):
                chunk = source.recv(remaining)
            else:
                chunk = source.read(remaining)
        except (socket.timeout, TimeoutError) as exc:
            raise FrameError("frame read timed out") from exc
        except OSError as exc:
            raise FrameError(f"frame read failed: {exc}") from exc
        if not chunk:
            raise FrameError("truncated frame")
        if not isinstance(chunk, bytes):
            raise FrameError("frame source must return bytes")
        parts.append(chunk)
        remaining -= len(chunk)
    return b"".join(parts)
