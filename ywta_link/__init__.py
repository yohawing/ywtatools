"""YWTA Link v1の依存なしProtocol foundation。"""

from .contract import NegotiationResult, SyncChannel, SyncContract
from .client import LinkClient, LinkClientError
from .envelope import Envelope, decode_envelope, encode_envelope
from .frame import Frame, FrameError, FrameLimits, decode_frame, encode_frame, read_frame, write_frame
from .session import ChannelRevisionTracker, SessionState, SyncSession
from .runtime import RuntimeError, RuntimeManifest, read_runtime_manifest, resolve_broker_executable

__all__ = (
    "ChannelRevisionTracker",
    "Envelope",
    "Frame",
    "FrameError",
    "FrameLimits",
    "LinkClient",
    "LinkClientError",
    "NegotiationResult",
    "SessionState",
    "SyncChannel",
    "SyncContract",
    "SyncSession",
    "RuntimeError",
    "RuntimeManifest",
    "decode_envelope",
    "decode_frame",
    "encode_envelope",
    "encode_frame",
    "read_frame",
    "read_runtime_manifest",
    "resolve_broker_executable",
    "write_frame",
)
