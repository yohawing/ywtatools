"""Common Camera v1のAuthority付き同期component。"""

from __future__ import annotations

from ._snapshot_sync import (
    SnapshotController,
    SnapshotEchoGuard,
    SnapshotHandoffCoordinator,
    SnapshotHandoffStatus,
    SnapshotSyncError,
    SnapshotSyncRuntime,
    SnapshotSyncStatus,
    SnapshotSyncThreadError,
    SnapshotTopicTransport,
)
from .camera import CAMERA_SCHEMA, Camera, CameraValidationError

CameraSyncError = SnapshotSyncError
CameraSyncThreadError = SnapshotSyncThreadError
CameraControllerStatus = SnapshotSyncStatus
CameraHandoffStatus = SnapshotHandoffStatus


class CameraEchoGuard(SnapshotEchoGuard):
    """Camera remote changeのechoを有界に抑止する。"""


class CameraController(SnapshotController):
    """Camera Authority、publish/apply、echo抑止を束ねる。"""

    snapshot_type = Camera
    local_type = Camera
    guard_type = CameraEchoGuard


class CameraTopicTransport(SnapshotTopicTransport):
    """Camera Common v1専用Topic transport。"""

    schema = CAMERA_SCHEMA
    snapshot_type = Camera
    validation_error = CameraValidationError
    controller_type = CameraController


class CameraHandoffCoordinator(SnapshotHandoffCoordinator):
    """Camera変更に伴うAuthority handoffを管理する。"""


class CameraSyncRuntime(SnapshotSyncRuntime):
    """Camera同期componentをDCC Main Thread上で束ねる。"""


__all__ = (
    "CameraController",
    "CameraControllerStatus",
    "CameraEchoGuard",
    "CameraHandoffCoordinator",
    "CameraHandoffStatus",
    "CameraSyncError",
    "CameraSyncRuntime",
    "CameraSyncThreadError",
    "CameraTopicTransport",
)
