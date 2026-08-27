"""YWTA Link v1の依存なしProtocol foundation。"""

from .contract import NegotiationResult, SyncChannel, SyncContract
from .camera import CAMERA_FIELDS, CAMERA_SCHEMA, FILM_FIT_VALUES, GATE_FIT_VALUES, Camera, CameraValidationError
from .client import LinkClient, LinkClientError
from .entity_ref import (
    ENTITY_REFERENCE_FIELDS,
    ENTITY_REFERENCE_SCHEMA,
    EntityReference,
    EntityReferenceValidationError,
)
from .envelope import Envelope, decode_envelope, encode_envelope
from .frame import Frame, FrameError, FrameLimits, decode_frame, encode_frame, read_frame, write_frame
from .presence import (
    PEER_HELLO_SCHEMA,
    PRESENCE_MAX_CAPABILITIES,
    PRESENCE_MAX_CAPABILITY_LENGTH,
    PRESENCE_MAX_PROTOCOL_VERSION,
    PRESENCE_MAX_PROTOCOL_VERSIONS,
    PRESENCE_MAX_STRING_LENGTH,
    PeerPresence,
    PresenceValidationError,
)
from .session import ChannelRevisionTracker, SessionState, SyncSession
from .runtime import RuntimeError, RuntimeManifest, read_runtime_manifest, resolve_broker_executable
from .time import RATE_FIELDS, TIME_FIELDS, TIME_SCHEMA, RationalRate, Time, TimeValidationError

__all__ = (
    "ChannelRevisionTracker",
    "CAMERA_FIELDS",
    "CAMERA_SCHEMA",
    "FILM_FIT_VALUES",
    "GATE_FIT_VALUES",
    "Camera",
    "CameraValidationError",
    "ENTITY_REFERENCE_FIELDS",
    "ENTITY_REFERENCE_SCHEMA",
    "EntityReference",
    "EntityReferenceValidationError",
    "Envelope",
    "Frame",
    "FrameError",
    "FrameLimits",
    "LinkClient",
    "LinkClientError",
    "PEER_HELLO_SCHEMA",
    "PRESENCE_MAX_CAPABILITIES",
    "PRESENCE_MAX_CAPABILITY_LENGTH",
    "PRESENCE_MAX_PROTOCOL_VERSION",
    "PRESENCE_MAX_PROTOCOL_VERSIONS",
    "PRESENCE_MAX_STRING_LENGTH",
    "PeerPresence",
    "PresenceValidationError",
    "RATE_FIELDS",
    "RationalRate",
    "TIME_FIELDS",
    "TIME_SCHEMA",
    "Time",
    "TimeValidationError",
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
