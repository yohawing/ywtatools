"""Common Camera Sessionのautomatic bootstrap facade。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from ._session_bootstrap import ConnectionFactory, PlaybackBootstrapError, bootstrap_session
from .camera import CAMERA_SCHEMA
from .camera_session import CameraSession, CameraSessionConfig, compose_camera_session
from .errors import _non_negative_finite, _positive_finite, _validate_identifier
from .presence import PeerPresence

CAMERA_SLOT_METADATA_FIELDS = frozenset({"contract_version", "channel_id", "camera_schema"})
CameraBootstrapError = PlaybackBootstrapError


@dataclass(frozen=True)
class CameraBootstrapConfig:
    """DCC Adapterが渡すCamera bootstrap設定。"""

    application_id: str
    application: str
    application_version: str
    plugin_version: str
    room: str = "default"
    slot_id: str = "camera-default.v1"
    channel_id: str = "camera"
    topic: str = "camera"
    bootstrap_timeout: float = 1.0
    max_attempts: int = 3
    queue_capacity: int = 256
    stop_timeout: float = 1.0
    handoff_timeout: float = 1.0

    def __post_init__(self) -> None:
        for name in (
            "application_id",
            "application",
            "application_version",
            "plugin_version",
            "room",
            "slot_id",
            "channel_id",
            "topic",
        ):
            _validate_identifier(getattr(self, name), name, CameraBootstrapError)
        if not _positive_finite(self.bootstrap_timeout):
            raise CameraBootstrapError("bootstrap_timeout must be a positive finite number")
        if isinstance(self.max_attempts, bool) or not isinstance(self.max_attempts, int) or not 1 <= self.max_attempts <= 16:
            raise CameraBootstrapError("max_attempts must be an integer from 1 to 16")
        if isinstance(self.queue_capacity, bool) or not isinstance(self.queue_capacity, int) or self.queue_capacity <= 0:
            raise CameraBootstrapError("queue_capacity must be a positive integer")
        if not _non_negative_finite(self.stop_timeout):
            raise CameraBootstrapError("stop_timeout must be a non-negative finite number")
        if not _positive_finite(self.handoff_timeout):
            raise CameraBootstrapError("handoff_timeout must be a positive finite number")

    @property
    def slot_metadata(self) -> dict[str, Any]:
        return {"contract_version": 1, "channel_id": self.channel_id, "camera_schema": CAMERA_SCHEMA}

    def presence(self, peer_id: str) -> PeerPresence:
        return PeerPresence(
            peer_id=peer_id,
            application=self.application,
            application_version=self.application_version,
            plugin_version=self.plugin_version,
            protocol_versions=(1,),
            capabilities=("camera.apply.v1", "camera.read.v1", "sync.authority.v1"),
        )

    def validate_slot_metadata(self, value: object) -> None:
        if not isinstance(value, Mapping) or set(value) != CAMERA_SLOT_METADATA_FIELDS:
            raise CameraBootstrapError("Camera slot metadata has unknown or missing fields")
        if type(value["contract_version"]) is not int or value["contract_version"] != 1:
            raise CameraBootstrapError("Camera slot metadata contract_version must be integer 1")
        if value["channel_id"] != self.channel_id:
            raise CameraBootstrapError("Camera slot metadata channel_id does not match config")
        if value["camera_schema"] != CAMERA_SCHEMA:
            raise CameraBootstrapError("Camera slot metadata camera_schema does not match Camera")

    def build_session_config(self, peer_id: str, session_id: str, authority: str) -> CameraSessionConfig:
        return CameraSessionConfig(
            peer_id,
            session_id,
            self.room,
            self.topic,
            self.channel_id,
            authority,
            self.queue_capacity,
            self.stop_timeout,
            self.handoff_timeout,
        )


def bootstrap_camera_session(
    config: CameraBootstrapConfig,
    host_factory: Callable[[object], object],
    lifecycle_factory: Callable[[object, object], object],
    connection_factory: ConnectionFactory | None = None,
) -> CameraSession:
    """Camera slotとAuthorityをreconcileし、未開始Sessionを返す。"""

    return bootstrap_session(
        config,
        CameraBootstrapConfig,
        host_factory,
        lifecycle_factory,
        compose_camera_session,
        connection_factory,
        "Camera",
    )


__all__ = (
    "CAMERA_SLOT_METADATA_FIELDS",
    "CameraBootstrapConfig",
    "CameraBootstrapError",
    "bootstrap_camera_session",
)
