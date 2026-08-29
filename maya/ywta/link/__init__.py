"""YWTA Link向けMaya Adapter。"""

from .camera_host import (
    MayaCameraBinding,
    MayaCameraHost,
    MayaCameraHostError,
    MayaCameraHostUnavailableError,
)
from .camera_lifecycle import (
    MayaCameraLifecycle,
    MayaCameraLifecycleError,
    MayaCameraLifecycleStatus,
    MayaCameraLifecycleUnavailableError,
)
from .camera_session import (
    bootstrap_maya_camera_session,
    compose_maya_camera_session,
    default_maya_camera_config,
)
from .lifecycle import (
    MayaPlaybackLifecycle,
    MayaPlaybackLifecycleError,
    MayaPlaybackLifecycleStatus,
    MayaPlaybackLifecycleUnavailableError,
)
from .playback_host import (
    MAYA_PLAYBACK_EVENTS,
    CallbackErrorStatus,
    MayaPlaybackHost,
    MayaPlaybackHostError,
    MayaPlaybackHostUnavailableError,
)
from .session import (
    bootstrap_maya_playback_session,
    compose_maya_playback_session,
    default_maya_playback_config,
)
from ywta_link.playback_host import (
    PlaybackHostEvent,
    PlaybackHostEventKind,
    PlaybackHostRange,
    PlaybackHostSnapshot,
    PlaybackHostValidationError,
)

__all__ = (
    "CallbackErrorStatus",
    "MAYA_PLAYBACK_EVENTS",
    "MayaCameraBinding",
    "MayaCameraHost",
    "MayaCameraHostError",
    "MayaCameraHostUnavailableError",
    "MayaCameraLifecycle",
    "MayaCameraLifecycleError",
    "MayaCameraLifecycleStatus",
    "MayaCameraLifecycleUnavailableError",
    "MayaPlaybackHost",
    "MayaPlaybackHostError",
    "MayaPlaybackHostUnavailableError",
    "MayaPlaybackLifecycle",
    "MayaPlaybackLifecycleError",
    "MayaPlaybackLifecycleStatus",
    "MayaPlaybackLifecycleUnavailableError",
    "bootstrap_maya_camera_session",
    "bootstrap_maya_playback_session",
    "compose_maya_playback_session",
    "compose_maya_camera_session",
    "default_maya_camera_config",
    "default_maya_playback_config",
    "PlaybackHostEvent",
    "PlaybackHostEventKind",
    "PlaybackHostRange",
    "PlaybackHostSnapshot",
    "PlaybackHostValidationError",
)
