"""Immutable Common snapshot同期で再利用するprivateな実行基盤。"""

from __future__ import annotations

import math
import threading
import time
import weakref
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .adapter import AdapterDispatch
from .authority import (
    AUTHORITY_ACCEPTED_SCHEMA,
    AUTHORITY_REJECTED_SCHEMA,
    AUTHORITY_REQUEST_SCHEMA,
    AuthorityHandoffRequest,
    AuthorityHandoffTracker,
)
from .authority_transport import AuthorityHandoffTransport
from .errors import AuthorityViolation, _bounded_error_details, _bounded_error_message, _validate_identifier
from .frame import Frame
from ._topic_lease import claim_topic, release_topic


class SnapshotSyncError(RuntimeError):
    """Snapshot同期の構成、状態、wire失敗。"""


class SnapshotSyncThreadError(SnapshotSyncError):
    """owner thread以外からの操作。"""


@dataclass(frozen=True)
class SnapshotErrorInfo:
    """Component失敗の型名と上限付きmessage。"""

    exception_type: str
    message: str


@dataclass(frozen=True)
class SnapshotSyncStatus:
    """共通componentの軽量な状態。"""

    closed: bool
    failed: bool
    error: SnapshotErrorInfo | None


class SnapshotEchoGuard:
    """Remote changeを有界に記録するecho guard。"""

    def __init__(self, capacity: int = 256) -> None:
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity <= 0:
            raise SnapshotSyncError("echo capacity must be a positive integer")
        self._capacity = capacity
        self._keys: set[tuple[str, str]] = set()
        self._order: deque[tuple[str, str]] = deque()

    def remember(self, origin: str, change_id: str) -> None:
        key = (_identifier(origin, "origin_peer_id"), _identifier(change_id, "change_id"))
        if key in self._keys:
            return
        if len(self._order) == self._capacity:
            self._keys.remove(self._order.popleft())
        self._order.append(key)
        self._keys.add(key)

    def should_publish(self, origin: str, change_id: str) -> bool:
        return (_identifier(origin, "origin_peer_id"), _identifier(change_id, "change_id")) not in self._keys


_CLAIMED_SNAPSHOT_GUARDS: weakref.WeakSet[object] = weakref.WeakSet()
_CLAIMED_SNAPSHOT_GUARDS_LOCK = threading.Lock()


class SnapshotTopicTransport:
    """一つのRoom/Topicへimmutable Common snapshotを接続する。"""

    schema: str
    snapshot_type: type[Any]
    validation_error: type[Exception]
    controller_type: type[Any]
    error_type: type[Exception] = SnapshotSyncError
    thread_error_type: type[Exception] = SnapshotSyncThreadError
    label = "snapshot"

    def __init__(self, client: object, room: str, topic: str) -> None:
        for method_name in ("publish", "subscribe", "unsubscribe"):
            if not callable(getattr(client, method_name, None)):
                raise self.error_type(f"client must provide callable {method_name}()")
        self._client = client
        self._room = _validate_identifier(room, "room", self.error_type)
        self._topic = _validate_identifier(topic, "topic", self.error_type)
        _validate_identifier(self.schema, "schema", self.error_type)
        self._owner = threading.get_ident()
        self.active = False
        self.closed = False
        claim_topic(client, self.room, self.topic, self, self.error_type)

    @property
    def client(self) -> object:
        return self._client

    @property
    def room(self) -> str:
        return self._room

    @property
    def topic(self) -> str:
        return self._topic

    def subscribe(self) -> bool:
        self._require_owner()
        self._require_open()
        if self.active:
            return False
        self._call("subscribe", self.client.subscribe, self.room, self.topic)
        self.active = True
        return True

    def publish(self, snapshot: object) -> str:
        self._require_owner()
        self._require_open()
        if not self.active:
            raise self.error_type(f"{self.label} transport is not subscribed")
        if type(snapshot) is not self.snapshot_type:
            raise self.error_type(f"{self.label} must be exactly a {self.snapshot_type.__name__}")
        result = self._call(
            "publish",
            self.client.publish,
            self.room,
            topic=self.topic,
            schema=self.schema,
            body=snapshot.to_dict(),
        )
        if not isinstance(result, str) or not result:
            raise self.error_type("client.publish() must return a non-empty string message ID")
        return result

    def handle_frame(self, frame: Frame, controller: "SnapshotController") -> bool:
        self._require_owner()
        self._require_open()
        if not self.active:
            raise self.error_type(f"{self.label} transport is not subscribed")
        if type(frame) is not Frame:
            raise self.error_type("frame must be exactly a Frame")
        if type(controller) is not self.controller_type:
            raise self.error_type(f"controller must be exactly a {self.controller_type.__name__}")
        envelope = frame.envelope
        if envelope.type != "publish" or envelope.room != self.room or envelope.topic != self.topic:
            return False
        if envelope.schema != self.schema:
            raise self.error_type(f"{self.label} frame schema does not match transport schema")
        if frame.body or not isinstance(envelope.body, Mapping):
            raise self.error_type(f"{self.label} frame requires a JSON object and no raw body")
        try:
            snapshot = self.snapshot_type.from_dict(envelope.body)
        except self.validation_error as exc:
            raise self.error_type(f"invalid {self.label} frame body: {_bounded_error_message(exc)}") from exc
        try:
            result = controller.apply_remote(envelope.sender, snapshot)
        except Exception as exc:
            raise self.error_type(f"controller.apply_remote() failed: {_bounded_error_message(exc)}") from exc
        if not isinstance(result, bool):
            raise self.error_type("controller.apply_remote() must return bool")
        return result

    def close(self) -> bool:
        self._require_owner()
        if self.closed:
            return False
        if self.active:
            self._call("unsubscribe", self.client.unsubscribe, self.room, self.topic)
            self.active = False
        self.closed = True
        release_topic(self.client, self.room, self.topic, self)
        return True

    def _call(self, operation: str, method: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        try:
            return method(*args, **kwargs)
        except self.error_type:
            raise
        except Exception as exc:
            raise self.error_type(f"client.{operation}() failed: {_bounded_error_message(exc)}") from exc

    def _require_owner(self) -> None:
        if threading.get_ident() != self._owner:
            raise self.thread_error_type(f"{self.label} transport operation must run on its owner thread")

    def _require_open(self) -> None:
        if self.closed:
            raise self.error_type(f"{self.label} transport is closed")


class SnapshotController:
    """Authority、publish/apply、echo抑止をimmutable snapshotへ適用する。"""

    snapshot_type: type[Any]
    local_type: type[Any]
    guard_type: type[Any] = SnapshotEchoGuard
    error_type: type[Exception] = SnapshotSyncError
    thread_error_type: type[Exception] = SnapshotSyncThreadError
    label = "snapshot"

    def __init__(
        self,
        peer_id: str,
        channel_id: str,
        authority_provider: Callable[[str], str],
        publisher: Callable[[Any], object],
        host_apply: Callable[[Any], object],
        echo_guard: SnapshotEchoGuard | None = None,
    ) -> None:
        self._peer_id = _validate_identifier(peer_id, "peer_id", self.error_type)
        self._channel_id = _validate_identifier(channel_id, "channel_id", self.error_type)
        for value, name in ((authority_provider, "authority_provider"), (publisher, "publisher"), (host_apply, "host_apply")):
            if not callable(value):
                raise self.error_type(f"{name} must be callable")
        self._authority_provider = authority_provider
        self._publisher = publisher
        self._host_apply = host_apply
        if echo_guard is not None and not isinstance(echo_guard, self.guard_type):
            raise self.error_type(f"echo_guard must be a {self.guard_type.__name__} or None")
        self._guard = echo_guard or self.guard_type()
        with _CLAIMED_SNAPSHOT_GUARDS_LOCK:
            if self._guard in _CLAIMED_SNAPSHOT_GUARDS:
                raise self.error_type("echo_guard is already owned by another Controller")
            _CLAIMED_SNAPSHOT_GUARDS.add(self._guard)
        self._owner = threading.get_ident()
        self._closed = False
        self._failed = False
        self._error: SnapshotErrorInfo | None = None
        self._status_lock = threading.Lock()
        self._operation: str | None = None

    @property
    def status(self) -> SnapshotSyncStatus:
        with self._status_lock:
            return SnapshotSyncStatus(self._closed, self._failed, self._error)

    @property
    def peer_id(self) -> str:
        return self._peer_id

    @property
    def channel_id(self) -> str:
        return self._channel_id

    def handle_host_change(self, snapshot: object, origin_peer_id: str | None = None) -> bool:
        self._require_owner()
        if type(snapshot) is not self.local_type:
            raise self.error_type(f"{self.label} must be a {self.local_type.__name__}")
        if not self._usable():
            return False
        origin = (
            self.peer_id if origin_peer_id is None else _validate_identifier(origin_peer_id, "origin_peer_id", self.error_type)
        )
        try:
            should_publish = self._guard_should_publish(origin, self._change_id(snapshot))
        except Exception as exc:
            self._fail(exc)
            raise
        if not should_publish:
            return False
        if self._operation is not None:
            self._fail(self.error_type(f"handle_host_change cannot run during {self._operation}"))
        try:
            if _validate_identifier(self._authority_provider(self.channel_id), "authority", self.error_type) != self.peer_id:
                return False
            self._operation = "publish"
            self._publisher(self._to_wire(snapshot))
            return True
        except Exception as exc:
            self._fail(exc)
            raise
        finally:
            self._operation = None

    def apply_remote(self, origin_peer_id: str, snapshot: object) -> bool:
        self._require_owner()
        if not self._usable():
            return False
        if type(snapshot) is not self.snapshot_type:
            raise self.error_type(f"{self.label} must be a {self.snapshot_type.__name__}")
        origin = _validate_identifier(origin_peer_id, "origin_peer_id", self.error_type)
        if origin == self.peer_id:
            return False
        try:
            authority = _validate_identifier(self._authority_provider(self.channel_id), "authority", self.error_type)
        except Exception as exc:
            self._fail(exc)
            raise
        if origin != authority:
            raise AuthorityViolation(f"origin is not authority for channel: {self.channel_id!r}")
        try:
            if self._operation is not None:
                self._fail(self.error_type(f"apply_remote cannot run during {self._operation}"))
            self._guard_remember(origin, self._change_id(snapshot))
            self._operation = "apply"
            self._host_apply(self._to_host(snapshot))
            return True
        except Exception as exc:
            self._fail(exc)
            raise
        finally:
            self._operation = None

    def close(self) -> bool:
        self._require_owner()
        with self._status_lock:
            if self._closed:
                return False
        if self._operation is not None:
            self._fail(self.error_type(f"close cannot run during {self._operation}"))
        with self._status_lock:
            self._closed = True
        return True

    def _usable(self) -> bool:
        with self._status_lock:
            return not self._closed and not self._failed

    def _require_owner(self) -> None:
        if threading.get_ident() != self._owner:
            raise self.thread_error_type(f"{self.label} Controller operation must run on its owner thread")

    def _fail(self, error: BaseException) -> None:
        with self._status_lock:
            self._failed = True
            self._error = SnapshotErrorInfo(*_bounded_error_details(error))
        if isinstance(error, self.error_type):
            raise error

    def _to_wire(self, value: Any) -> Any:
        return value

    def _to_host(self, value: Any) -> Any:
        return value

    def _change_id(self, value: Any) -> str:
        return value.change_id

    def _guard_should_publish(self, origin: str, change_id: str) -> bool:
        return self._guard.should_publish(origin, change_id)

    def _guard_remember(self, origin: str, change_id: str) -> None:
        self._guard.remember(origin, change_id)


@dataclass(frozen=True)
class SnapshotHandoffStatus:
    """Authority handoffの状態。"""

    pending: bool
    failed: bool
    closed: bool
    error: SnapshotErrorInfo | None


class SnapshotHandoffCoordinator:
    """Snapshot変更とAuthority handoffの順序を管理する。"""

    def __init__(
        self,
        peer_id: str,
        channel_id: str,
        tracker: AuthorityHandoffTracker,
        authority_transport: AuthorityHandoffTransport,
        controller: SnapshotController,
        initial_snapshot: object,
        rollback_apply: Callable[[Any], object],
        handoff_timeout: float,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.peer_id = _identifier(peer_id, "peer_id")
        self.channel_id = _identifier(channel_id, "channel_id")
        if type(tracker) is not AuthorityHandoffTracker or type(authority_transport) is not AuthorityHandoffTransport:
            raise SnapshotSyncError("tracker and authority_transport must use exact Link types")
        if controller.peer_id != self.peer_id or controller.channel_id != self.channel_id:
            raise SnapshotSyncError("controller identity must match handoff identity")
        if authority_transport.tracker is not tracker:
            raise SnapshotSyncError("authority_transport must use the supplied tracker")
        if type(initial_snapshot) is not controller.snapshot_type:
            raise SnapshotSyncError("initial_snapshot type must match Controller")
        if not callable(rollback_apply) or not callable(monotonic_clock):
            raise SnapshotSyncError("rollback_apply and monotonic_clock must be callable")
        if (
            isinstance(handoff_timeout, bool)
            or not isinstance(handoff_timeout, (int, float))
            or not math.isfinite(float(handoff_timeout))
            or handoff_timeout <= 0
        ):
            raise SnapshotSyncError("handoff_timeout must be a positive finite number")
        tracker.state_for(self.channel_id)
        self.tracker = tracker
        self.authority_transport = authority_transport
        self.controller = controller
        self._baseline = initial_snapshot
        self._rollback_apply = rollback_apply
        self._timeout = float(handoff_timeout)
        self._clock = monotonic_clock
        self._owner = threading.get_ident()
        self._deadline: float | None = None
        self._retained: object | None = None
        self._accepted_response_seen = False
        self._closed = False
        self._failed = False
        self._error: SnapshotErrorInfo | None = None
        self._status_lock = threading.Lock()

    @property
    def status(self) -> SnapshotHandoffStatus:
        with self._status_lock:
            return SnapshotHandoffStatus(self._deadline is not None, self._failed, self._closed, self._error)

    def handle_host_change(self, snapshot: object) -> bool:
        self._require_usable()
        if type(snapshot) is not self.controller.snapshot_type:
            raise SnapshotSyncError("snapshot type must match Controller")
        try:
            state = self.tracker.state_for(self.channel_id)
            if state.authority == self.peer_id:
                published = self.controller.handle_host_change(snapshot)
                if published:
                    self._baseline = snapshot
                return published
            self._retained = snapshot
            if self.tracker.pending_for(self.channel_id) is not None:
                return False
            request = AuthorityHandoffRequest(
                self.tracker.session_id,
                self.channel_id,
                state.authority,
                self.peer_id,
                state.revision,
                snapshot.change_id,
            )
            self.authority_transport.request_handoff(request)
            self._deadline = self._new_deadline()
            self._accepted_response_seen = False
            return False
        except Exception as exc:
            self._fail(exc)
            raise SnapshotSyncError(f"handle_host_change failed: {_bounded_error_message(exc)}") from exc

    def handle_authority_frame(self, frame: Frame) -> bool:
        self._require_usable()
        before = self.tracker.pending_for(self.channel_id)
        try:
            if self.authority_transport.handle_frame(frame) is not True:
                return False
            envelope = frame.envelope
            if envelope.type == "request" and envelope.schema == AUTHORITY_REQUEST_SCHEMA:
                state = self.tracker.state_for(self.channel_id)
                pending = self.tracker.pending_for(self.channel_id)
                if state.authority == self.peer_id and pending is not None:
                    self.authority_transport.accept_handoff(pending.request)
                return True
            after = self.tracker.pending_for(self.channel_id)
            state = self.tracker.state_for(self.channel_id)
            if envelope.type == "response" and envelope.schema == AUTHORITY_ACCEPTED_SCHEMA:
                if envelope.correlation_id == getattr(before, "request_message_id", None) and not self._accepted_response_seen:
                    self._deadline = self._new_deadline()
                    self._accepted_response_seen = True
                return True
            if envelope.type == "response" and envelope.schema == AUTHORITY_REJECTED_SCHEMA:
                if before is not None and after is None:
                    self._restore()
                return True
            if (
                envelope.type == "publish"
                and envelope.schema == AUTHORITY_ACCEPTED_SCHEMA
                and before is not None
                and after is None
            ):
                if state.authority != self.peer_id or envelope.correlation_id != getattr(before, "request_message_id", None):
                    self._restore()
                elif self._retained is not None:
                    retained = self._retained
                    self._rollback_apply(retained)
                    if self.controller.handle_host_change(retained) is not True:
                        raise SnapshotSyncError("accepted handoff snapshot was not published")
                    self._baseline = retained
                    self._clear_pending()
            return True
        except Exception as exc:
            self._fail(exc)
            raise SnapshotSyncError(f"handle_authority_frame failed: {_bounded_error_message(exc)}") from exc

    def observe_authoritative_snapshot(self, snapshot: object) -> None:
        self._require_usable()
        if type(snapshot) is not self.controller.snapshot_type:
            raise SnapshotSyncError("snapshot type must match Controller")
        self._baseline = snapshot

    def poll_timeout(self) -> bool:
        self._require_usable()
        try:
            if self._deadline is None or self._now() < self._deadline:
                return False
            self._restore()
            error = SnapshotSyncError("Authority handoff timed out")
            self._fail(error)
            return True
        except Exception as exc:
            self._fail(exc)
            raise SnapshotSyncError(f"poll_timeout failed: {_bounded_error_message(exc)}") from exc

    def close(self) -> bool:
        self._require_owner()
        with self._status_lock:
            if self._closed:
                return False
            self._closed = True
        self._clear_pending()
        return True

    def _restore(self) -> None:
        self._rollback_apply(self._baseline)
        self._clear_pending()

    def _clear_pending(self) -> None:
        self._retained = None
        self._deadline = None
        self._accepted_response_seen = False

    def _new_deadline(self) -> float:
        return self._now() + self._timeout

    def _now(self) -> float:
        value = self._clock()
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise SnapshotSyncError("monotonic_clock must return a finite number")
        return float(value)

    def _require_owner(self) -> None:
        if threading.get_ident() != self._owner:
            raise SnapshotSyncThreadError("snapshot handoff operation must run on its owner thread")

    def _require_usable(self) -> None:
        self._require_owner()
        with self._status_lock:
            if self._closed or self._failed:
                raise SnapshotSyncError("snapshot handoff Coordinator is closed or failed")

    def _fail(self, error: BaseException) -> None:
        with self._status_lock:
            if not self._failed:
                self._failed = True
                self._error = SnapshotErrorInfo(*_bounded_error_details(error))


@dataclass(frozen=True)
class SnapshotRuntimeStatus:
    """Runtimeの開始、終了、失敗状態。"""

    started: bool
    closed: bool
    failed: bool
    error: SnapshotErrorInfo | None


_CLAIMED_RUNTIME_COMPONENTS: weakref.WeakSet[object] = weakref.WeakSet()
_CLAIMED_RUNTIME_COMPONENTS_LOCK = threading.Lock()


class SnapshotSyncRuntime:
    """Adapter dispatch、Authority、snapshot componentを一つに束ねる。"""

    def __init__(
        self,
        dispatch: AdapterDispatch,
        authority_transport: AuthorityHandoffTransport,
        transport: SnapshotTopicTransport,
        controller: SnapshotController,
        coordinator: SnapshotHandoffCoordinator,
    ) -> None:
        if type(dispatch) is not AdapterDispatch:
            raise SnapshotSyncError("dispatch must be exactly an AdapterDispatch")
        if dispatch.client is not authority_transport.client or dispatch.client is not transport.client:
            raise SnapshotSyncError("dispatch and transports must share the same Client")
        if coordinator.authority_transport is not authority_transport or coordinator.controller is not controller:
            raise SnapshotSyncError("coordinator components must match Runtime")
        if authority_transport.room != transport.room or authority_transport.topic == transport.topic:
            raise SnapshotSyncError("transports require one Room and distinct topics")
        if coordinator.peer_id != authority_transport.client.peer_id:
            raise SnapshotSyncError("coordinator peer_id must match Client")
        with _CLAIMED_RUNTIME_COMPONENTS_LOCK:
            components = (dispatch, authority_transport, transport, controller, coordinator)
            if any(component in _CLAIMED_RUNTIME_COMPONENTS for component in components):
                raise SnapshotSyncError("snapshot component is already owned by another Runtime")
            _CLAIMED_RUNTIME_COMPONENTS.update(components)
        self.dispatch = dispatch
        self.authority_transport = authority_transport
        self.transport = transport
        self.controller = controller
        self.coordinator = coordinator
        self._owner = threading.get_ident()
        self._started = False
        self._closed = False
        self._failed = False
        self._error: SnapshotErrorInfo | None = None
        self._status_lock = threading.Lock()

    @property
    def status(self) -> SnapshotRuntimeStatus:
        with self._status_lock:
            return SnapshotRuntimeStatus(self._started, self._closed, self._failed, self._error)

    def start(self) -> bool:
        self._require_owner()
        with self._status_lock:
            if self._closed or self._failed:
                raise SnapshotSyncError("snapshot Runtime is closed or failed")
            if self._started:
                return False
        try:
            if self.authority_transport.subscribe() is not True:
                raise SnapshotSyncError("AuthorityHandoffTransport.subscribe() must return True")
            if self.transport.subscribe() is not True:
                raise SnapshotSyncError("snapshot transport subscribe() must return True")
            if self.dispatch.start() is not True:
                raise SnapshotSyncError("AdapterDispatch.start() must return True")
            with self._status_lock:
                self._started = True
            return True
        except Exception as exc:
            self._mark_failed(exc)
            try:
                self.close()
            except Exception as rollback_error:
                raise SnapshotSyncError(
                    f"snapshot Runtime start failed and rollback failed: {_bounded_error_message(rollback_error)}"
                ) from exc
            raise

    def pump(self, max_items: int | None = None) -> int:
        self._require_owner()
        with self._status_lock:
            if not self._started or self._closed or self._failed:
                raise SnapshotSyncError("snapshot Runtime is not running")
        try:
            receiver_error = self.dispatch.status.receiver_error
            if receiver_error is not None:
                raise SnapshotSyncError(f"Adapter receiver failed: {receiver_error.message}")
            count = self.dispatch.drain(self._handle_frame, max_items)
            timed_out = self.coordinator.poll_timeout()
            coordinator_status = self.coordinator.status
            if timed_out or coordinator_status.failed:
                raise SnapshotSyncError("Authority handoff timed out or Coordinator failed")
            return count
        except Exception as exc:
            self._mark_failed(exc)
            raise

    def close(self) -> bool:
        self._require_owner()
        with self._status_lock:
            if self._closed:
                return False
        errors: list[BaseException] = []
        for component in (self.coordinator, self.authority_transport, self.transport):
            try:
                component.close()
            except BaseException as exc:
                errors.append(exc)
        if not errors:
            try:
                if self.dispatch.close_session() is not True:
                    errors.append(SnapshotSyncError("AdapterDispatch.close_session() did not stop"))
            except BaseException as exc:
                errors.append(exc)
            try:
                self.controller.close()
            except BaseException as exc:
                errors.append(exc)
        if errors:
            self._mark_failed(errors[0])
            raise SnapshotSyncError(f"snapshot Runtime close failed: {_bounded_error_message(errors[0])}") from errors[0]
        with self._status_lock:
            self._closed = True
        return True

    def _handle_frame(self, frame: Frame) -> None:
        if not self.coordinator.handle_authority_frame(frame):
            self.transport.handle_frame(frame, self.controller)

    def _require_owner(self) -> None:
        if threading.get_ident() != self._owner:
            raise SnapshotSyncThreadError("snapshot Runtime operation must run on its owner thread")

    def _mark_failed(self, error: BaseException) -> None:
        with self._status_lock:
            self._failed = True
            self._error = SnapshotErrorInfo(*_bounded_error_details(error))


class OwnedSyncSession:
    """DCC lifecycle、Runtime、専用Clientの終了順序を共通化する。"""

    error_type: type[Exception] = SnapshotSyncError
    session_name = "SnapshotSession"
    runtime_name = "SnapshotSyncRuntime"

    def __init__(self, lifecycle: object, authority_tracker: AuthorityHandoffTracker, runtime: object, client: object) -> None:
        if not callable(getattr(lifecycle, "start", None)) or not callable(getattr(lifecycle, "close", None)):
            raise self.error_type("lifecycle must provide start() and close()")
        self.lifecycle = lifecycle
        self.authority_tracker = authority_tracker
        self._runtime = runtime
        self.runtime = runtime
        self._client = client
        self._owner_thread_id = threading.get_ident()
        self._started = False
        self._start_attempted = False
        self._cleanup_completed = False
        self._closed = False

    @property
    def authority_transport(self) -> AuthorityHandoffTransport:
        return self._runtime.authority_transport

    def start(self) -> bool:
        self._require_owner()
        if self._closed:
            raise self.error_type(f"{self.session_name} is closed")
        if self._started:
            return False
        self._start_attempted = True
        result = self.lifecycle.start()
        if result is not True:
            raise self.error_type("lifecycle.start() must return True")
        self._started = True
        return True

    def close(self) -> bool:
        self._require_owner()
        if self._closed:
            return False
        if not self._cleanup_completed:
            if self._start_attempted:
                self._close_lifecycle()
            else:
                self._close_runtime()
            self._cleanup_completed = True
        try:
            self._client.close()
        except BaseException as error:
            raise self.error_type("client.close() failed") from error
        self._closed = True
        return True

    def _close_runtime(self) -> None:
        try:
            self._runtime.close()
        except BaseException as error:
            raise self.error_type(f"{self.runtime_name}.close() failed") from error

    def _close_lifecycle(self) -> None:
        try:
            result = self.lifecycle.close()
        except BaseException as error:
            raise self.error_type("lifecycle.close() failed") from error
        if result is not True and getattr(getattr(self.lifecycle, "status", None), "closed", False) is not True:
            raise self.error_type("lifecycle.close() must return True unless lifecycle is already closed")

    def _require_owner(self) -> None:
        if threading.get_ident() != self._owner_thread_id:
            raise self.error_type(f"{self.session_name} operation must run on its owner thread")


def _identifier(value: object, field_name: str) -> str:
    return _validate_identifier(value, field_name, SnapshotSyncError)
