"""YWTA Link v1の主要な利用者向けAPI。

Wire定数や低レベルI/Oは、定義元のサブモジュールから明示的にimportする。
"""

from .authority import (
    AuthorityHandoffAccepted,
    AuthorityHandoffRejected,
    AuthorityHandoffRequest,
    AuthorityHandoffTracker,
    AuthoritySnapshot,
    AuthoritySnapshotRequest,
    AuthorityState,
    AuthorityValidationError,
)
from .authority_transport import AuthorityHandoffTransport, AuthorityTransportError, AuthorityTransportThreadError
from .camera import Camera, CameraValidationError
from .client import LinkClient, LinkClientError
from .contract import NegotiationResult, SyncChannel, SyncContract
from .entity_ref import EntityReference, EntityReferenceValidationError
from .envelope import Envelope
from .frame import Frame, FrameError
from .playback import Playback, PlaybackEchoGuard, PlaybackValidationError
from .playback_bootstrap import PlaybackBootstrapConfig, PlaybackBootstrapError, bootstrap_playback_session
from .playback_controller import (
    PlaybackController,
    PlaybackControllerError,
    PlaybackControllerThreadError,
)
from .playback_handoff import PlaybackHandoffCoordinator, PlaybackHandoffError, PlaybackHandoffThreadError
from .playback_host import (
    PlaybackHostEvent,
    PlaybackHostEventKind,
    PlaybackHostRange,
    PlaybackHostSnapshot,
    PlaybackHostValidationError,
)
from .playback_mapping import PlaybackTimeMapper, PlaybackTimeMappingError
from .playback_session import PlaybackSession, PlaybackSessionConfig, PlaybackSessionError, compose_playback_session
from .playback_sync import PlaybackSyncRuntime, PlaybackSyncRuntimeError
from .playback_transport import PlaybackTopicTransport, PlaybackTransportError, PlaybackTransportThreadError
from .presence import PeerPresence, PresenceValidationError
from .runtime import RuntimeManifest, resolve_broker_executable
from .session import ChannelRevisionTracker, SessionState, SyncSession
from .time import RationalRate, Time, TimeValidationError
from .transform import CoordinateSystem, Transform, TransformValidationError

__all__ = (
    "AuthorityHandoffAccepted",
    "AuthorityHandoffRejected",
    "AuthorityHandoffRequest",
    "AuthorityHandoffTracker",
    "AuthorityHandoffTransport",
    "AuthoritySnapshot",
    "AuthoritySnapshotRequest",
    "AuthorityState",
    "AuthorityTransportError",
    "AuthorityTransportThreadError",
    "AuthorityValidationError",
    "Camera",
    "CameraValidationError",
    "ChannelRevisionTracker",
    "CoordinateSystem",
    "EntityReference",
    "EntityReferenceValidationError",
    "Envelope",
    "Frame",
    "FrameError",
    "LinkClient",
    "LinkClientError",
    "NegotiationResult",
    "PeerPresence",
    "Playback",
    "PlaybackBootstrapConfig",
    "PlaybackBootstrapError",
    "PlaybackController",
    "PlaybackControllerError",
    "PlaybackControllerThreadError",
    "PlaybackEchoGuard",
    "PlaybackHandoffError",
    "PlaybackHandoffCoordinator",
    "PlaybackHandoffThreadError",
    "PlaybackHostEvent",
    "PlaybackHostEventKind",
    "PlaybackHostRange",
    "PlaybackHostSnapshot",
    "PlaybackHostValidationError",
    "PlaybackSession",
    "PlaybackSessionConfig",
    "PlaybackSessionError",
    "PlaybackSyncRuntime",
    "PlaybackSyncRuntimeError",
    "PlaybackTimeMapper",
    "PlaybackTimeMappingError",
    "PlaybackTopicTransport",
    "PlaybackTransportError",
    "PlaybackTransportThreadError",
    "PlaybackValidationError",
    "PresenceValidationError",
    "RationalRate",
    "RuntimeManifest",
    "SessionState",
    "SyncChannel",
    "SyncContract",
    "SyncSession",
    "Time",
    "TimeValidationError",
    "Transform",
    "TransformValidationError",
    "bootstrap_playback_session",
    "compose_playback_session",
    "resolve_broker_executable",
)
