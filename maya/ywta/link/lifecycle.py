"""Maya上のPlayback同期SessionのMain Thread lifecycleを管理する。"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable

from .playback_host import CallbackErrorStatus


class MayaPlaybackLifecycleError(RuntimeError):
    """Playback同期Sessionの設定、状態、またはcleanup失敗を表す。"""


class MayaPlaybackLifecycleUnavailableError(MayaPlaybackLifecycleError):
    """MayaまたはQtの実行環境が利用できない。"""


@dataclass(frozen=True)
class MayaPlaybackLifecycleStatus:
    """Playback同期Sessionの軽量な状態snapshot。"""

    started: bool
    closed: bool
    failed: bool
    timer_running: bool
    exit_callback_registered: bool
    error: CallbackErrorStatus | None


class MayaPlaybackLifecycle:
    """構成済みRuntimeとHostをMaya Main Threadへ接続する。"""

    def __init__(
        self,
        runtime: Any,
        host: Any,
        *,
        timer: Any = None,
        timer_factory: Callable[[], Any] | None = None,
        scene_message: Any = None,
        message: Any = None,
        timer_interval_ms: int = 100,
        max_pump_items: int | None = 64,
    ) -> None:
        """Client、Room、Authorityを生成せず、既存componentを受け取る。"""

        for component, methods, name in (
            (runtime, ("start", "pump", "close"), "runtime"),
            (host, ("register", "unregister"), "host"),
        ):
            _require_methods(component, methods, name)
        if timer is not None and timer_factory is not None:
            raise MayaPlaybackLifecycleError("timer and timer_factory are mutually exclusive")
        if timer_factory is not None and not callable(timer_factory):
            raise MayaPlaybackLifecycleError("timer_factory must be callable")
        if isinstance(timer_interval_ms, bool) or not isinstance(timer_interval_ms, int) or timer_interval_ms <= 0:
            raise MayaPlaybackLifecycleError("timer_interval_ms must be a positive integer")
        if max_pump_items is not None and (
            isinstance(max_pump_items, bool) or not isinstance(max_pump_items, int) or max_pump_items < 0
        ):
            raise MayaPlaybackLifecycleError("max_pump_items must be a non-negative integer or None")

        self._runtime = runtime
        self._host = host
        self._owner_thread_id = threading.get_ident()
        self._timer_interval_ms = timer_interval_ms
        self._max_pump_items = max_pump_items
        self._started = False
        self._closed = False
        self._failed = False
        self._start_attempted = False
        self._runtime_started = False
        self._host_registered = False
        self._timer_running = False
        self._exit_callback_id: Any = None
        self._last_error: CallbackErrorStatus | None = None
        self._error_count = 0
        self._timer = timer if timer is not None else self._make_timer(timer_factory)
        self._connect_timer()
        self._scene_message, self._message = _resolve_maya_messages(scene_message, message)
        _require_methods(self._scene_message, ("addCallback",), "scene_message")
        _require_methods(self._message, ("removeCallback",), "message")

    @property
    def owner_thread_id(self) -> int:
        """Sessionを生成したMaya Main ThreadのIDを返す。"""

        return self._owner_thread_id

    @property
    def exit_callback_id(self) -> Any:
        """実際に登録されているMaya exiting callback IDを返す。"""

        return self._exit_callback_id

    @property
    def callback_ids(self) -> tuple[Any, ...]:
        """実際に残っているcallback IDのsnapshotを返す。"""

        if self._exit_callback_id is None:
            return ()
        return (self._exit_callback_id,)

    @property
    def last_error(self) -> CallbackErrorStatus | None:
        """隔離された最後の例外情報を返す。"""

        return self._last_error

    @property
    def failed(self) -> bool:
        """Lifecycle自身またはHostのterminal failureを返す。"""

        return self._failed or bool(getattr(self._host, "failed", False))

    @property
    def status(self) -> MayaPlaybackLifecycleStatus:
        """Sessionの軽量な状態snapshotを返す。"""

        host_failed = bool(getattr(self._host, "failed", False))
        host_error = getattr(self._host, "last_error", None) if host_failed else None
        return MayaPlaybackLifecycleStatus(
            started=self._started,
            closed=self._closed,
            failed=self.failed,
            timer_running=self._timer_running,
            exit_callback_registered=self._exit_callback_id is not None,
            error=self._last_error or host_error,
        )

    def start(self) -> bool:
        """Runtime、Host、timer、exiting callbackの順に開始する。"""

        self._assert_owner_thread("start")
        if self._closed or self._started:
            return False
        if self._start_attempted:
            raise MayaPlaybackLifecycleError("MayaPlaybackLifecycle start has already failed")
        self._start_attempted = True

        try:
            if self._host_is_registered():
                raise MayaPlaybackLifecycleError("MayaPlaybackHost is already registered")
            if self._runtime.start() is not True:
                raise MayaPlaybackLifecycleError("PlaybackSyncRuntime.start() must return True")
            self._runtime_started = True
            try:
                host_result = self._host.register()
            except BaseException:
                self._host_registered = self._host_is_registered()
                raise
            if host_result is not True:
                self._host_registered = self._host_is_registered()
                raise MayaPlaybackLifecycleError("MayaPlaybackHost.register() must return True")
            self._host_registered = True

            self._timer_running = True
            self._timer.start()
            event = getattr(self._scene_message, "kMayaExiting", None)
            if event is None:
                raise MayaPlaybackLifecycleUnavailableError("MSceneMessage.kMayaExiting is unavailable")
            callback_id = self._scene_message.addCallback(event, self._on_maya_exiting)
            if callback_id is None:
                raise MayaPlaybackLifecycleError("MSceneMessage.addCallback() returned no callback ID")
            self._exit_callback_id = callback_id
        except BaseException as error:
            self._record_error("start", error)
            rollback_errors = self._rollback_start()
            self._failed = True
            if rollback_errors:
                self._record_error("rollback", rollback_errors[-1])
                detail = "Maya playback lifecycle start failed and rollback failed"
                raise self._lifecycle_error(detail, error) from error
            self._closed = True
            raise self._lifecycle_error("Maya playback lifecycle start failed", error) from error

        self._started = True
        return True

    def close(self) -> bool:
        """timer、Host、Runtime、Maya exiting callbackの順に段階終了する。"""

        self._assert_owner_thread("close")
        if self._closed:
            return False
        if not self._has_resources():
            self._closed = True
            return False

        errors: list[BaseException] = []
        self._stop_timer(errors)
        if not errors:
            self._unregister_host(errors)
        if not errors:
            self._close_runtime(errors)
        if not errors:
            self._remove_exit_callback(errors)
        if errors:
            self._failed = True
            self._record_error("close", errors[0])
            raise self._lifecycle_error("Maya playback lifecycle close failed", errors[0]) from errors[0]

        self._started = False
        self._closed = True
        return True

    def _on_timer(self) -> None:
        """QTimer callbackでRuntimeのpump例外を隔離する。"""

        if self._closed or not self._started or not self._timer_running:
            return
        if self.failed:
            stop_errors: list[BaseException] = []
            self._stop_timer(stop_errors)
            if stop_errors:
                self._record_error("timer_stop", stop_errors[0])
            return
        try:
            self._assert_owner_thread("timer callback")
            if self._max_pump_items is None:
                self._runtime.pump()
            else:
                self._runtime.pump(max_items=self._max_pump_items)
        except BaseException as error:
            self._failed = True
            self._record_error("timer", error)
            stop_errors: list[BaseException] = []
            self._stop_timer(stop_errors)
            if stop_errors:
                self._record_error("timer_stop", stop_errors[0])

    def _on_maya_exiting(self, *_args: Any) -> None:
        """Maya終了callbackからMain Thread cleanupを開始する。"""

        try:
            self.close()
        except BaseException as error:
            self._failed = True
            self._record_error("maya_exiting", error)

    def _rollback_start(self) -> list[BaseException]:
        """開始失敗時に依存順でcomponentを解放する。"""

        errors: list[BaseException] = []
        self._stop_timer(errors)
        if not errors:
            self._unregister_host(errors)
        if not errors:
            self._close_runtime(errors)
        if not errors:
            self._remove_exit_callback(errors)
        if not errors and not self._has_resources():
            self._closed = True
        return errors

    def _stop_timer(self, errors: list[BaseException]) -> None:
        """timer停止を試み、失敗時は再試行用にrunning台帳を保持する。"""

        if not self._timer_running:
            return
        try:
            self._timer.stop()
        except BaseException as error:
            errors.append(error)
        else:
            self._timer_running = False

    def _remove_exit_callback(self, errors: list[BaseException]) -> None:
        """MMessage.removeCallbackを実IDへ適用し、成功時だけ台帳から除く。"""

        if self._exit_callback_id is None:
            return
        try:
            self._message.removeCallback(self._exit_callback_id)
        except BaseException as error:
            errors.append(error)
        else:
            self._exit_callback_id = None

    def _unregister_host(self, errors: list[BaseException]) -> None:
        """Host callback解除を試み、失敗時は後続cleanupを保留する。"""

        if not self._host_registered:
            return
        try:
            self._host.unregister()
        except BaseException as error:
            errors.append(error)
        else:
            self._host_registered = False

    def _close_runtime(self, errors: list[BaseException]) -> None:
        """Runtime closeを試み、失敗時は次回closeへ残す。"""

        if not self._runtime_started:
            return
        try:
            self._runtime.close()
        except BaseException as error:
            errors.append(error)
        else:
            self._runtime_started = False

    def _host_is_registered(self) -> bool:
        """Hostが既にcallbackを持つかを観測する。"""

        return bool(getattr(self._host, "registered", False))

    def _has_resources(self) -> bool:
        """解放対象のcomponentが残っているかを返す。"""

        return self._runtime_started or self._host_registered or self._timer_running or self._exit_callback_id is not None

    def _connect_timer(self) -> None:
        """QTimerのintervalとstable callbackを設定する。"""

        set_interval = getattr(self._timer, "setInterval", None)
        if callable(set_interval):
            set_interval(self._timer_interval_ms)
        timeout = getattr(self._timer, "timeout", None)
        connect = getattr(timeout, "connect", None)
        if not callable(connect):
            raise MayaPlaybackLifecycleUnavailableError("QTimer.timeout.connect is unavailable")
        connect(self._on_timer)

    @staticmethod
    def _make_timer(timer_factory: Callable[[], Any] | None) -> Any:
        """注入factoryまたはPySide6/PySide2 fallbackからQTimerを作る。"""

        if timer_factory is not None:
            timer = timer_factory()
            if timer is None:
                raise MayaPlaybackLifecycleError("timer_factory returned no timer")
            return timer
        try:
            from PySide6.QtCore import QTimer
        except ImportError:
            try:
                from PySide2.QtCore import QTimer
            except ImportError as error:
                raise MayaPlaybackLifecycleUnavailableError("PySide6 or PySide2 QTimer is unavailable; inject timer") from error
        return QTimer()

    def _assert_owner_thread(self, operation: str) -> None:
        """操作をSession生成元のMaya Main Threadに限定する。"""

        if threading.get_ident() != self._owner_thread_id:
            raise MayaPlaybackLifecycleError(f"{operation} must run on the Maya Main Thread")

    def _record_error(self, callback: str, error: BaseException) -> None:
        """例外本体を保持せず、型名とmessageだけを保存する。"""

        self._error_count += 1
        try:
            message = str(error)
        except BaseException:
            message = "<unprintable exception>"
        self._last_error = CallbackErrorStatus(callback, type(error).__name__, message[:1024], self._error_count)

    @staticmethod
    def _lifecycle_error(prefix: str, error: BaseException) -> MayaPlaybackLifecycleError:
        """内部例外を公開境界の型へ変換する。"""

        try:
            message = str(error)
        except BaseException:
            message = "<unprintable exception>"
        return MayaPlaybackLifecycleError(f"{prefix}: {message[:1024]}")


def _require_methods(component: Any, methods: tuple[str, ...], name: str) -> None:
    """注入componentの最小interfaceを検証する。"""

    for method in methods:
        if not callable(getattr(component, method, None)):
            raise MayaPlaybackLifecycleError(f"{name}.{method} is unavailable")


def _resolve_maya_messages(scene_message: Any, message: Any) -> tuple[Any, Any]:
    """未指定のMaya message APIだけを遅延importで解決する。"""

    if scene_message is not None and message is not None:
        return scene_message, message
    try:
        import maya.api.OpenMaya as open_maya
    except ImportError as error:
        raise MayaPlaybackLifecycleUnavailableError(
            "Maya Python API is unavailable; inject scene_message and message"
        ) from error
    if scene_message is None:
        scene_message = getattr(open_maya, "MSceneMessage", None)
    if message is None:
        message = getattr(open_maya, "MMessage", None)
    if scene_message is None or message is None:
        raise MayaPlaybackLifecycleUnavailableError("MSceneMessage and MMessage are unavailable")
    return scene_message, message


__all__ = (
    "MayaPlaybackLifecycle",
    "MayaPlaybackLifecycleError",
    "MayaPlaybackLifecycleStatus",
    "MayaPlaybackLifecycleUnavailableError",
)
