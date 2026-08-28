"""DCC非依存なPlayback同期Sessionの最小構成。"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from typing import Callable

from .adapter import AdapterDispatch
from .authority import AuthorityHandoffTracker
from .client import LinkClient
from .playback_controller import PlaybackController
from .playback_host import PlaybackHostEvent
from .playback_mapping import PlaybackTimeMapper
from .playback_sync import PlaybackSyncRuntime
from .playback_transport import PlaybackTopicTransport


class PlaybackSessionError(RuntimeError):
    """Playback Sessionの構成または終了に失敗したことを表す。"""


@dataclass(frozen=True)
class PlaybackSessionConfig:
    """DCC Adapterが明示して渡すPlayback Session設定。"""

    peer_id: str
    session_id: str
    room: str
    topic: str
    channel_id: str
    initial_authority: str
    ticks_per_host_unit: int
    host_unit_rate: object
    time_unit: str
    queue_capacity: int = 256
    stop_timeout: float = 1.0

    def __post_init__(self) -> None:
        """暗黙のRoom、Authority、timebaseを許可しない。"""

        for name in ("peer_id", "session_id", "room", "topic", "channel_id", "initial_authority", "time_unit"):
            _identifier(getattr(self, name), name)
        if isinstance(self.queue_capacity, bool) or not isinstance(self.queue_capacity, int) or self.queue_capacity <= 0:
            raise PlaybackSessionError("queue_capacity must be a positive integer")
        if (
            isinstance(self.stop_timeout, bool)
            or not isinstance(self.stop_timeout, (int, float))
            or not math.isfinite(float(self.stop_timeout))
            or self.stop_timeout < 0
        ):
            raise PlaybackSessionError("stop_timeout must be a non-negative finite number")
        try:
            PlaybackTimeMapper(
                ticks_per_host_unit=self.ticks_per_host_unit,
                host_unit_rate=self.host_unit_rate,
                time_unit=self.time_unit,
            )
        except (TypeError, ValueError) as error:
            raise PlaybackSessionError(f"invalid playback timebase: {error}") from error


class PlaybackSession:
    """専用Clientを所有し、DCC Lifecycleへ開始と終了を委譲する。"""

    def __init__(
        self,
        lifecycle: object,
        authority_tracker: AuthorityHandoffTracker,
        runtime: PlaybackSyncRuntime,
        client: object,
    ) -> None:
        """構成済みで未開始のSessionを初期化する。"""

        if not callable(getattr(lifecycle, "start", None)) or not callable(getattr(lifecycle, "close", None)):
            raise PlaybackSessionError("lifecycle must provide start() and close()")
        self.lifecycle = lifecycle
        self.authority_tracker = authority_tracker
        self._runtime = runtime
        self._client = client
        self._owner_thread_id = threading.get_ident()
        self._started = False
        self._start_attempted = False
        self._cleanup_completed = False
        self._closed = False

    def start(self) -> bool:
        """Lifecycleを一度だけ開始する。"""

        self._require_owner()
        if self._closed:
            raise PlaybackSessionError("PlaybackSession is closed")
        if self._started:
            return False
        self._start_attempted = True
        result = self.lifecycle.start()
        if result is not True:
            raise PlaybackSessionError("lifecycle.start() must return True")
        self._started = True
        return True

    def close(self) -> bool:
        """Lifecycle成功後だけClientを閉じ、失敗時は終了を再試行可能にする。"""

        self._require_owner()
        if self._closed:
            return False
        if not self._cleanup_completed:
            if self._start_attempted:
                self._close_lifecycle()
            else:
                self._close_runtime()
            self._cleanup_completed = True
        self._close_client()
        self._closed = True
        return True

    def _close_runtime(self) -> None:
        """未開始または開始rollback済みRuntimeを直接終了する。"""

        try:
            self._runtime.close()
        except BaseException as error:
            raise PlaybackSessionError("PlaybackSyncRuntime.close() failed") from error

    def _close_lifecycle(self) -> None:
        """開始試行済みLifecycleを閉じ、rollback済み状態だけFalseを許可する。"""

        try:
            result = self.lifecycle.close()
        except BaseException as error:
            raise PlaybackSessionError("lifecycle.close() failed") from error
        if result is True:
            return
        status = getattr(self.lifecycle, "status", None)
        if getattr(status, "closed", False) is not True:
            raise PlaybackSessionError("lifecycle.close() must return True unless lifecycle is already closed")

    def _close_client(self) -> None:
        """専用Clientを明示的に終了する。"""

        try:
            self._client.close()
        except BaseException as error:
            raise PlaybackSessionError("client.close() failed") from error

    def _require_owner(self) -> None:
        """DCC Main Thread以外からのlifecycle操作を拒否する。"""

        if threading.get_ident() != self._owner_thread_id:
            raise PlaybackSessionError("PlaybackSession operation must run on its owner thread")


def compose_playback_session(
    config: PlaybackSessionConfig,
    host_factory: Callable[[Callable[[PlaybackHostEvent], bool]], object],
    lifecycle_factory: Callable[[object, PlaybackSyncRuntime], object],
    client_factory: Callable[[PlaybackSessionConfig], LinkClient] | None = None,
) -> PlaybackSession:
    """専用Client、Host、Runtime、Lifecycleを未開始Sessionとして構成する。"""

    if not isinstance(config, PlaybackSessionConfig):
        raise PlaybackSessionError("config must be a PlaybackSessionConfig")
    if not callable(host_factory) or not callable(lifecycle_factory):
        raise PlaybackSessionError("host_factory and lifecycle_factory must be callable")
    factory = _default_client_factory if client_factory is None else client_factory
    if not callable(factory):
        raise PlaybackSessionError("client_factory must be callable")

    client: object | None = None
    transport: PlaybackTopicTransport | None = None
    controller: PlaybackController | None = None
    runtime: PlaybackSyncRuntime | None = None
    try:
        client = factory(config)
        _require_methods(client, ("join", "close", "receive", "publish", "subscribe", "unsubscribe"), "client")
        client.join(config.room)
        mapper = PlaybackTimeMapper(
            ticks_per_host_unit=config.ticks_per_host_unit,
            host_unit_rate=config.host_unit_rate,
            time_unit=config.time_unit,
        )
        tracker = AuthorityHandoffTracker({config.channel_id: config.initial_authority}, config.session_id)
        relay = _HostRelay()
        host = host_factory(relay)
        _require_methods(host, ("apply",), "host")
        transport = PlaybackTopicTransport(client, config.room, config.topic)
        controller = PlaybackController(
            config.peer_id,
            config.channel_id,
            mapper,
            lambda channel_id: tracker.state_for(channel_id).authority,
            transport.publish,
            host.apply,
        )
        relay.bind(controller.handle_host_event)
        dispatch = AdapterDispatch(client, queue_capacity=config.queue_capacity, stop_timeout=config.stop_timeout)
        runtime = PlaybackSyncRuntime(dispatch, transport, controller)
        lifecycle = lifecycle_factory(host, runtime)
        return PlaybackSession(lifecycle, tracker, runtime, client)
    except BaseException as error:
        rollback_errors = _rollback_construction(runtime, transport, controller, client)
        if rollback_errors:
            detail = "; ".join(_error_text(rollback_error) for rollback_error in rollback_errors)
            raise PlaybackSessionError(f"PlaybackSession construction rollback failed: {detail}") from error
        raise


def _default_client_factory(config: PlaybackSessionConfig) -> LinkClient:
    """設定済みPeer IDでBrokerへ接続または起動する。"""

    return LinkClient.connect_or_start(config.peer_id)


class _HostRelay:
    """Host生成時のcallbackと後続Controllerを一度だけ接続する。"""

    def __init__(self) -> None:
        self._handler: Callable[[PlaybackHostEvent], bool] | None = None

    def __call__(self, event: PlaybackHostEvent) -> bool:
        """bind済みControllerへHost eventを渡す。"""

        if self._handler is None:
            raise PlaybackSessionError("host callback arrived before PlaybackController binding")
        return self._handler(event)

    def bind(self, handler: Callable[[PlaybackHostEvent], bool]) -> None:
        """ControllerのHost event handlerを一度だけ登録する。"""

        if self._handler is not None:
            raise PlaybackSessionError("host callback relay is already bound")
        self._handler = handler


def _identifier(value: object, name: str) -> None:
    """空白だけでないUTF-8識別子を検証する。"""

    if not isinstance(value, str) or not value or not value.strip():
        raise PlaybackSessionError(f"{name} must be a non-whitespace string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise PlaybackSessionError(f"{name} must be valid UTF-8") from error


def _require_methods(value: object, names: tuple[str, ...], name: str) -> None:
    """依存objectが必要最小限の操作を持つことを検証する。"""

    if any(not callable(getattr(value, method, None)) for method in names):
        raise PlaybackSessionError(f"{name} does not provide required methods")


def _rollback_construction(
    runtime: PlaybackSyncRuntime | None,
    transport: PlaybackTopicTransport | None,
    controller: PlaybackController | None,
    client: object | None,
) -> list[BaseException]:
    """構成途中のleaseと専用Clientをbest effortで解放する。"""

    errors: list[BaseException] = []
    if runtime is not None:
        try:
            runtime.close()
        except BaseException as error:
            errors.append(error)
    else:
        if transport is not None:
            try:
                transport.close()
            except BaseException as error:
                errors.append(error)
        if controller is not None:
            try:
                controller.close()
            except BaseException as error:
                errors.append(error)
    if client is not None:
        try:
            client.close()
        except BaseException as error:
            errors.append(error)
    return errors


def _error_text(error: BaseException) -> str:
    """cleanup例外を公開例外message向けの短い文字列へ変換する。"""

    try:
        return f"{type(error).__name__}: {str(error)[:1024]}"
    except Exception:
        return f"{type(error).__name__}: <unprintable exception>"


__all__ = ("PlaybackSessionConfig", "PlaybackSession", "PlaybackSessionError", "compose_playback_session")
