"""DCC非依存なCommon Camera同期Sessionの構成。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .adapter import AdapterDispatch
from ._snapshot_sync import OwnedSyncSession
from .authority import AuthorityHandoffTracker
from .authority_transport import AuthorityHandoffTransport
from .camera import Camera
from .camera_sync import (
    CameraController,
    CameraHandoffCoordinator,
    CameraSyncRuntime,
    CameraTopicTransport,
)
from .client import LinkClient
from .errors import _bounded_error_message, _non_negative_finite, _positive_finite, _validate_identifier


class CameraSessionError(RuntimeError):
    """Camera Sessionの構成または終了失敗。"""


@dataclass(frozen=True)
class CameraSessionConfig:
    """DCC Adapterが渡すCamera Session設定。"""

    peer_id: str
    session_id: str
    room: str
    topic: str
    channel_id: str
    initial_authority: str
    queue_capacity: int = 256
    stop_timeout: float = 1.0
    handoff_timeout: float = 1.0

    def __post_init__(self) -> None:
        for name in ("peer_id", "session_id", "room", "topic", "channel_id", "initial_authority"):
            _validate_identifier(getattr(self, name), name, CameraSessionError)
        if self.topic == f"sync/{self.session_id}/control":
            raise CameraSessionError("topic must differ from the Session control topic")
        if isinstance(self.queue_capacity, bool) or not isinstance(self.queue_capacity, int) or self.queue_capacity <= 0:
            raise CameraSessionError("queue_capacity must be a positive integer")
        if not _non_negative_finite(self.stop_timeout):
            raise CameraSessionError("stop_timeout must be a non-negative finite number")
        if not _positive_finite(self.handoff_timeout):
            raise CameraSessionError("handoff_timeout must be a positive finite number")


class CameraSession(OwnedSyncSession):
    """専用ClientとCamera runtimeのlifecycleを所有する。"""

    error_type = CameraSessionError
    session_name = "CameraSession"
    runtime_name = "CameraSyncRuntime"


def compose_camera_session(
    config: CameraSessionConfig,
    host_factory: Callable[[Callable[[Camera], bool]], object],
    lifecycle_factory: Callable[[object, CameraSyncRuntime], object],
    client_factory: Callable[[CameraSessionConfig], LinkClient] | None = None,
    *,
    authority_tracker: AuthorityHandoffTracker | None = None,
) -> CameraSession:
    """Client、Host、Authority付きCamera runtimeを未開始Sessionへ構成する。"""

    if not isinstance(config, CameraSessionConfig):
        raise CameraSessionError("config must be a CameraSessionConfig")
    if not callable(host_factory) or not callable(lifecycle_factory):
        raise CameraSessionError("host_factory and lifecycle_factory must be callable")
    if authority_tracker is not None:
        _validate_tracker(authority_tracker, config)
    factory = _default_client_factory if client_factory is None else client_factory
    client: object | None = None
    components: list[object] = []
    runtime: CameraSyncRuntime | None = None
    try:
        client = factory(config)
        if getattr(client, "peer_id", None) != config.peer_id:
            raise CameraSessionError("client.peer_id must match config.peer_id")
        for method in ("join", "close", "receive", "publish", "subscribe", "unsubscribe", "request", "response"):
            if not callable(getattr(client, method, None)):
                raise CameraSessionError("client does not provide required methods")
        client.join(config.room)
        tracker = authority_tracker or AuthorityHandoffTracker({config.channel_id: config.initial_authority}, config.session_id)
        _validate_tracker(tracker, config)
        authority_transport = AuthorityHandoffTransport(client, config.room, tracker)
        components.append(authority_transport)
        transport = CameraTopicTransport(client, config.room, config.topic)
        components.append(transport)
        relay = _CameraRelay()
        host = host_factory(relay)
        if not callable(getattr(host, "snapshot", None)) or not callable(getattr(host, "apply", None)):
            raise CameraSessionError("host must provide snapshot() and apply()")
        initial_snapshot = host.snapshot()
        if type(initial_snapshot) is not Camera:
            raise CameraSessionError("host.snapshot() must return exactly a Camera")
        coordinator: CameraHandoffCoordinator | None = None

        def apply_remote(camera: Camera) -> None:
            host.apply(camera)
            if coordinator is None:
                raise CameraSessionError("Camera coordinator is not bound")
            coordinator.observe_authoritative_snapshot(camera)

        controller = CameraController(
            config.peer_id,
            config.channel_id,
            lambda channel_id: tracker.state_for(channel_id).authority,
            transport.publish,
            apply_remote,
        )
        components.append(controller)
        coordinator = CameraHandoffCoordinator(
            config.peer_id,
            config.channel_id,
            tracker,
            authority_transport,
            controller,
            initial_snapshot,
            host.apply,
            config.handoff_timeout,
        )
        components.append(coordinator)
        relay.bind(coordinator.handle_host_change)
        dispatch = AdapterDispatch(client, queue_capacity=config.queue_capacity, stop_timeout=config.stop_timeout)
        runtime = CameraSyncRuntime(dispatch, authority_transport, transport, controller, coordinator)
        lifecycle = lifecycle_factory(host, runtime)
        return CameraSession(lifecycle, tracker, runtime, client)
    except BaseException as exc:
        errors = _rollback(runtime, components, client)
        if errors:
            detail = "; ".join(_bounded_error_message(error) for error in errors)
            raise CameraSessionError(f"CameraSession construction rollback failed: {detail}") from exc
        raise


class _CameraRelay:
    def __init__(self) -> None:
        self._handler: Callable[[Camera], bool] | None = None

    def __call__(self, camera: Camera) -> bool:
        if self._handler is None:
            raise CameraSessionError("host callback arrived before CameraController binding")
        return self._handler(camera)

    def bind(self, handler: Callable[[Camera], bool]) -> None:
        if self._handler is not None:
            raise CameraSessionError("host callback relay is already bound")
        self._handler = handler


def _default_client_factory(config: CameraSessionConfig) -> LinkClient:
    return LinkClient.connect_or_start(config.peer_id)


def _validate_tracker(tracker: AuthorityHandoffTracker, config: CameraSessionConfig) -> None:
    if type(tracker) is not AuthorityHandoffTracker or tracker.session_id != config.session_id:
        raise CameraSessionError("authority_tracker session does not match config")
    state = tracker.state_for(config.channel_id)
    if state.authority != config.initial_authority:
        raise CameraSessionError("authority_tracker authority does not match config")


def _rollback(runtime: CameraSyncRuntime | None, components: list[object], client: object | None) -> list[BaseException]:
    errors: list[BaseException] = []
    if runtime is not None:
        try:
            runtime.close()
        except BaseException as exc:
            errors.append(exc)
    else:
        for component in reversed(components):
            try:
                component.close()  # type: ignore[attr-defined]
            except BaseException as exc:
                errors.append(exc)
    if client is not None:
        try:
            client.close()  # type: ignore[attr-defined]
        except BaseException as exc:
            errors.append(exc)
    return errors


__all__ = ("CameraSession", "CameraSessionConfig", "CameraSessionError", "compose_camera_session")
