"""構成済みYWTA Link playback componentのBlender Main Thread lifecycle。"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from typing import Any

from .link_playback import CallbackErrorStatus

try:
    import bpy as _BPY
except ImportError:  # Blender外の標準Pythonテストでは依存注入を使う。
    _BPY = None


class BlenderPlaybackLifecycleError(RuntimeError):
    """Blender playback lifecycleの状態またはcomponent失敗を表す。"""


class BlenderPlaybackLifecycleUnavailableError(BlenderPlaybackLifecycleError):
    """Blender timer APIが利用できない。"""


@dataclass(frozen=True)
class BlenderPlaybackLifecycleStatus:
    """Playback lifecycleの軽量な状態snapshot。"""

    started: bool
    closed: bool
    failed: bool
    timer_registered: bool
    error: CallbackErrorStatus | None


class BlenderPlaybackLifecycle:
    """既存HostとRuntimeをBlender Main Threadのtimerへ束ねる。"""

    def __init__(
        self,
        host: Any,
        runtime: Any,
        *,
        bpy_module: Any = None,
        timer_interval: float = 0.1,
        max_pump_items: int | None = None,
    ) -> None:
        """既存componentを借用し、生成元threadを所有threadとして記録する。"""

        if not callable(getattr(host, "register", None)) or not callable(getattr(host, "unregister", None)):
            raise BlenderPlaybackLifecycleError("host must provide register and unregister")
        if not callable(getattr(runtime, "start", None)) or not callable(getattr(runtime, "pump", None)):
            raise BlenderPlaybackLifecycleError("runtime must provide start and pump")
        if not callable(getattr(runtime, "close", None)):
            raise BlenderPlaybackLifecycleError("runtime must provide close")
        if isinstance(timer_interval, bool) or not isinstance(timer_interval, (int, float)):
            raise BlenderPlaybackLifecycleError("timer_interval must be a finite positive number")
        if not math.isfinite(float(timer_interval)) or timer_interval <= 0:
            raise BlenderPlaybackLifecycleError("timer_interval must be a finite positive number")
        if max_pump_items is not None and (
            isinstance(max_pump_items, bool) or not isinstance(max_pump_items, int) or max_pump_items < 0
        ):
            raise BlenderPlaybackLifecycleError("max_pump_items must be a non-negative integer or None")

        self._bpy = _BPY if bpy_module is None else bpy_module
        if self._bpy is None:
            raise BlenderPlaybackLifecycleUnavailableError("Blender Python API is unavailable; inject bpy_module for tests")
        self._host = host
        self._runtime = runtime
        self._timer_interval = float(timer_interval)
        self._max_pump_items = max_pump_items
        self._owner_thread_id = threading.get_ident()
        self._started = False
        self._closed = False
        self._failed = False
        self._timer_registered = False
        self._host_registered = False
        self._runtime_started = False
        self._last_error: CallbackErrorStatus | None = None
        self._error_count = 0
        self._timer_callback_wrapper = self._make_persistent_callback()

    @property
    def status(self) -> BlenderPlaybackLifecycleStatus:
        """現在のlifecycle状態を返す。"""

        return BlenderPlaybackLifecycleStatus(
            started=self._started,
            closed=self._closed,
            failed=self.failed,
            timer_registered=self._timer_registered,
            error=self.last_error,
        )

    @property
    def started(self) -> bool:
        """startに成功してcloseされていないかを返す。"""

        return self._started

    @property
    def owner_thread_id(self) -> int:
        """Sessionを生成したBlender Main ThreadのIDを返す。"""

        return self._owner_thread_id

    @property
    def closed(self) -> bool:
        """全componentの終了が完了したかを返す。"""

        return self._closed

    @property
    def failed(self) -> bool:
        """callbackまたはlifecycle操作が失敗したかを返す。"""

        return self._failed or bool(getattr(self._host, "failed", False))

    @property
    def timer_registered(self) -> bool:
        """timer callbackの台帳上の登録状態を返す。"""

        return self._timer_registered

    @property
    def last_error(self) -> CallbackErrorStatus | None:
        """直近の失敗を軽量statusとして返す。"""

        return self._last_error or getattr(self._host, "last_error", None)

    def start(self) -> bool:
        """Runtime、Host、pump timerの順で起動する。"""

        self._assert_owner_thread("start")
        if self._closed:
            raise BlenderPlaybackLifecycleError("BlenderPlaybackLifecycle is closed")
        if self._failed:
            raise BlenderPlaybackLifecycleError("BlenderPlaybackLifecycle has failed")
        if self._started:
            return False

        runtime_attempted = False
        host_attempted = False
        try:
            runtime_attempted = True
            if self._runtime.start() is not True:
                raise BlenderPlaybackLifecycleError("PlaybackSyncRuntime.start() must return True")
            self._runtime_started = True

            host_attempted = True
            if self._host.register() is not True:
                raise BlenderPlaybackLifecycleError("BlenderPlaybackHost.register() must return True")
            self._host_registered = True

            self._register_timer()
            self._started = True
            return True
        except BaseException as error:
            self._failed = True
            rollback_errors = self._rollback_start(
                runtime_attempted=runtime_attempted,
                host_attempted=host_attempted,
            )
            if not rollback_errors:
                self._closed = True
                self._started = False
            self._record_error("start", error)
            message = "BlenderPlaybackLifecycle start failed"
            if rollback_errors:
                message += " and rollback failed"
            raise BlenderPlaybackLifecycleError(message) from error

    def close(self) -> bool:
        """timer、Host、Runtimeの順で終了し、失敗対象だけ次回再試行する。"""

        self._assert_owner_thread("close")
        if self._closed:
            return False

        # 失敗した対象が残っている場合も実在台帳を再確認し、先頭から再試行する。
        try:
            if self._timer_registered:
                self._unregister_timer()
            if self._host_registered or bool(getattr(self._host, "registered", False)):
                self._host.unregister()
                self._host_registered = False
            if self._runtime_started or self._runtime_is_started():
                self._runtime.close()
                self._runtime_started = False
        except BaseException as error:
            self._failed = True
            self._record_error("close", error)
            raise BlenderPlaybackLifecycleError("BlenderPlaybackLifecycle close failed") from error

        self._started = False
        self._closed = True
        return True

    def _register_timer(self) -> None:
        """stable persistent timerを登録し、実在不明時も台帳を安全側へ更新する。"""

        timers = self._timers()
        register = getattr(timers, "register", None)
        if not callable(register):
            raise BlenderPlaybackLifecycleUnavailableError("bpy.app.timers.register is unavailable")
        try:
            register(
                self._timer_callback_wrapper,
                first_interval=self._timer_interval,
                persistent=True,
            )
        except BaseException:
            self._timer_registered = self._timer_presence() is not False
            raise
        self._timer_registered = True

    def _unregister_timer(self) -> None:
        """timerを解除し、解除失敗時はretry用に台帳を保持する。"""

        timers = self._timers()
        unregister = getattr(timers, "unregister", None)
        if not callable(unregister):
            raise BlenderPlaybackLifecycleUnavailableError("bpy.app.timers.unregister is unavailable")
        try:
            unregister(self._timer_callback_wrapper)
        except BaseException:
            self._timer_registered = self._timer_presence() is not False
            raise
        self._timer_registered = False

    def _rollback_start(self, *, runtime_attempted: bool, host_attempted: bool) -> list[BaseException]:
        """start失敗後、成功済みcomponentを逆順にbest effortで戻す。"""

        errors: list[BaseException] = []
        if self._timer_registered:
            try:
                self._unregister_timer()
            except BaseException as error:
                errors.append(error)
        if not errors and (self._host_registered or host_attempted and bool(getattr(self._host, "registered", False))):
            try:
                self._host.unregister()
            except BaseException as error:
                errors.append(error)
            else:
                self._host_registered = False
        if not errors and (self._runtime_started or runtime_attempted and self._runtime_is_started()):
            try:
                self._runtime.close()
            except BaseException as error:
                errors.append(error)
            else:
                self._runtime_started = False
        return errors

    def _timer_callback(self) -> float | None:
        """Main Thread timerでpumpし、例外時はNoneを返してtimerを停止する。"""

        if self._closed or not self._timer_registered or self.failed:
            self._timer_registered = False
            return None
        try:
            self._assert_owner_thread("timer callback")
            if self._max_pump_items is None:
                self._runtime.pump()
            else:
                self._runtime.pump(max_items=self._max_pump_items)
        except BaseException as error:
            self._failed = True
            self._record_error("pump", error)
            # None戻り値でBlender自身にも除去させつつ、fakeが台帳を持つ場合は即時解除する。
            try:
                self._unregister_timer()
            except BaseException:
                self._timer_registered = self._timer_presence() is True
            return None
        return self._timer_interval

    def _make_persistent_callback(self) -> Any:
        """再登録時も同じidentityを使うtimer wrapperを生成する。"""

        def callback() -> float | None:
            return self._timer_callback()

        callback.__name__ = "_ywta_link_playback_pump"
        return callback

    def _timers(self) -> Any:
        """bpy.app.timersを取得する。"""

        timers = getattr(getattr(self._bpy, "app", None), "timers", None)
        if timers is None:
            raise BlenderPlaybackLifecycleUnavailableError("bpy.app.timers is unavailable")
        return timers

    def _timer_presence(self) -> bool | None:
        """Blender公式APIを優先し、テストfakeではcallback台帳を観測する。"""

        try:
            timers = self._timers()
        except BaseException:
            return None
        is_registered = getattr(timers, "is_registered", None)
        if callable(is_registered):
            try:
                return bool(is_registered(self._timer_callback_wrapper))
            except BaseException:
                # APIが利用できないfakeだけ、下記の観測用fallbackへ進む。
                pass
        callbacks = getattr(timers, "callbacks", None)
        if callbacks is None:
            return None
        try:
            for entry in callbacks:
                candidate = entry[0] if isinstance(entry, tuple) else entry
                if candidate is self._timer_callback_wrapper:
                    return True
        except (TypeError, IndexError):
            return None
        return False

    def _runtime_is_started(self) -> bool:
        """Runtime statusが利用できる場合だけ起動状態を観測する。"""

        status = getattr(self._runtime, "status", None)
        return bool(getattr(status, "started", False)) and not bool(getattr(status, "closed", False))

    def _record_error(self, callback: str, error: BaseException) -> None:
        """例外本体を保持せず、boundedな型名とmessageを保存する。"""

        self._error_count += 1
        try:
            message = str(error)
        except Exception:
            message = "<unprintable exception>"
        self._last_error = CallbackErrorStatus(
            callback=callback,
            exception_type=type(error).__name__,
            message=message[:1024],
            count=self._error_count,
        )

    def _assert_owner_thread(self, operation: str) -> None:
        """Main Thread lifecycle操作を生成元threadへ限定する。"""

        if threading.get_ident() != self._owner_thread_id:
            raise BlenderPlaybackLifecycleError(f"{operation} must run on the Blender Main Thread")


__all__ = (
    "BlenderPlaybackLifecycle",
    "BlenderPlaybackLifecycleError",
    "BlenderPlaybackLifecycleStatus",
    "BlenderPlaybackLifecycleUnavailableError",
)
