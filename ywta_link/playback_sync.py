"""Playback同期の短命なMain Thread runtime。"""

from __future__ import annotations

import threading
import weakref
from dataclasses import dataclass

from .adapter import AdapterDispatch
from .frame import Frame
from .playback_controller import PlaybackController
from .playback_transport import PlaybackTopicTransport


_CLAIMED_COMPONENTS: weakref.WeakSet[object] = weakref.WeakSet()
_CLAIMED_COMPONENTS_LOCK = threading.Lock()


class PlaybackSyncRuntimeError(RuntimeError):
    """Playback同期runtimeの設定、状態、またはcomponent失敗を表す。"""


@dataclass(frozen=True)
class PlaybackSyncRuntimeErrorInfo:
    """Runtime Failed状態へ保存する短い失敗情報。"""

    exception_type: str
    message: str


@dataclass(frozen=True)
class PlaybackSyncRuntimeStatus:
    """Playback同期runtimeの軽量な状態snapshot。"""

    started: bool
    closed: bool
    failed: bool
    error: PlaybackSyncRuntimeErrorInfo | None


class PlaybackSyncRuntime:
    """三つの既存componentをDCC Main Thread上で一つのSessionに束ねる。"""

    def __init__(
        self,
        dispatch: AdapterDispatch,
        transport: PlaybackTopicTransport,
        controller: PlaybackController,
    ) -> None:
        """所有権を移されたcomponentを検証し、owner threadを記録する。"""

        if type(dispatch) is not AdapterDispatch:
            raise PlaybackSyncRuntimeError("dispatch must be exactly an AdapterDispatch")
        if type(transport) is not PlaybackTopicTransport:
            raise PlaybackSyncRuntimeError("transport must be exactly a PlaybackTopicTransport")
        if type(controller) is not PlaybackController:
            raise PlaybackSyncRuntimeError("controller must be exactly a PlaybackController")
        if dispatch.client is not transport.client:
            raise PlaybackSyncRuntimeError("dispatch and transport must share the same Client instance")
        _claim_components(dispatch, transport, controller)
        self._dispatch = dispatch
        self._transport = transport
        self._controller = controller
        self._owner_thread_id = threading.get_ident()
        self._status_lock = threading.Lock()
        self._started = False
        self._start_attempted = False
        self._closed = False
        self._failed = False
        self._error: PlaybackSyncRuntimeErrorInfo | None = None
        self._active_operation: str | None = None

    @property
    def status(self) -> PlaybackSyncRuntimeStatus:
        """Runtimeの状態snapshotを返す。"""

        with self._status_lock:
            return PlaybackSyncRuntimeStatus(self._started, self._closed, self._failed, self._error)

    def start(self) -> bool:
        """購読を先に開始し、成功した場合だけ受信dispatchを起動する。"""

        self._require_owner()
        self._enter("start")
        try:
            with self._status_lock:
                if self._closed:
                    raise PlaybackSyncRuntimeError("PlaybackSyncRuntime is closed")
                if self._failed:
                    raise PlaybackSyncRuntimeError("PlaybackSyncRuntime has failed")
                if self._start_attempted:
                    return False
                self._start_attempted = True

            try:
                if self._transport.subscribe() is not True:
                    raise PlaybackSyncRuntimeError("PlaybackTopicTransport.subscribe() must return True")
                if self._dispatch.start() is not True:
                    raise PlaybackSyncRuntimeError("AdapterDispatch.start() must return True")
            except Exception as error:
                rollback_errors = self._rollback_start()
                self._mark_failed(error)
                with self._status_lock:
                    self._closed = not rollback_errors
                if rollback_errors:
                    raise self._runtime_error(
                        "PlaybackSyncRuntime start failed and component rollback failed",
                        error,
                    ) from error
                raise self._runtime_error("PlaybackSyncRuntime start failed", error) from error

            with self._status_lock:
                self._started = True
            return True
        finally:
            self._leave()

    def pump(self, max_items: int | None = None) -> int:
        """受信queueをMain Threadで処理し、drain件数を返す。"""

        self._require_owner()
        self._enter("pump")
        try:
            self._require_running()
            try:
                self._raise_receiver_error()
                drained = self._dispatch.drain(self._handle_frame, max_items)
                self._raise_receiver_error()
                return drained
            except Exception as error:
                if not self.status.failed:
                    self._mark_failed(error)
                raise self._runtime_error("PlaybackSyncRuntime pump failed", error) from error
        finally:
            self._leave()

    def close(self) -> bool:
        """購読、dispatch、Controllerを順番に閉じる。"""

        self._require_owner()
        self._enter("close")
        try:
            with self._status_lock:
                if self._closed:
                    return False

            try:
                self._transport.close()
            except Exception as error:
                # unsubscribe失敗時は受信を止めず、次回closeで再試行する。
                raise self._runtime_error("PlaybackSyncRuntime unsubscribe failed", error) from error

            errors: list[BaseException] = []
            try:
                stopped = self._dispatch.close_session()
                if stopped is not True:
                    errors.append(PlaybackSyncRuntimeError("AdapterDispatch.close_session() did not stop"))
            except BaseException as error:
                errors.append(error)
            try:
                self._controller.close()
            except BaseException as error:
                errors.append(error)

            with self._status_lock:
                self._closed = True
            if errors:
                self._mark_failed(errors[0])
                raise self._runtime_error("PlaybackSyncRuntime close failed", errors[0]) from errors[0]
            return True
        finally:
            self._leave()

    def _handle_frame(self, frame: Frame) -> None:
        """Adapterから受け取ったFrameをbound transportへ渡す。"""

        self._transport.handle_frame(frame, self._controller)

    def _require_running(self) -> None:
        """pump可能なruntime状態を検証する。"""

        with self._status_lock:
            if self._closed:
                raise PlaybackSyncRuntimeError("PlaybackSyncRuntime is closed")
            if self._failed:
                raise PlaybackSyncRuntimeError("PlaybackSyncRuntime has failed")
            if not self._started:
                raise PlaybackSyncRuntimeError("PlaybackSyncRuntime has not started")

    def _rollback_start(self) -> list[BaseException]:
        """start失敗後に全componentを閉じ、receiverを残さない。"""

        errors: list[BaseException] = []
        try:
            self._transport.close()
        except BaseException as error:
            errors.append(error)
            # unsubscribeを再試行できるよう、Clientを所有するdispatchはまだ閉じない。
            return errors
        try:
            if self._dispatch.close_session() is not True:
                errors.append(PlaybackSyncRuntimeError("AdapterDispatch rollback did not stop"))
        except BaseException as error:
            errors.append(error)
        try:
            self._controller.close()
        except BaseException as error:
            errors.append(error)
        return errors

    def _raise_receiver_error(self) -> None:
        """background receiver失敗を正常idleとして扱わずFailedへ昇格する。"""

        receiver_error = self._dispatch.status.receiver_error
        if receiver_error is None:
            return
        message = f"AdapterDispatch receiver failed: {receiver_error.exception_type}: {receiver_error.message}"
        with self._status_lock:
            self._failed = True
            self._error = PlaybackSyncRuntimeErrorInfo(
                receiver_error.exception_type,
                receiver_error.message[:1024],
            )
        raise PlaybackSyncRuntimeError(message)

    def _mark_failed(self, error: BaseException) -> None:
        """失敗原因を型名と上限付きmessageだけで保存する。"""

        info = _error_info(error)
        with self._status_lock:
            self._failed = True
            self._error = info

    @staticmethod
    def _runtime_error(prefix: str, error: BaseException) -> PlaybackSyncRuntimeError:
        """内部例外から公開境界用の型付き例外を作る。"""

        return PlaybackSyncRuntimeError(f"{prefix}: {_error_message(error)}")

    def _require_owner(self) -> None:
        """Runtime操作を生成元threadに限定する。"""

        if threading.get_ident() != self._owner_thread_id:
            raise PlaybackSyncRuntimeError("PlaybackSyncRuntime operation must run on its owner thread")

    def _enter(self, operation: str) -> None:
        """同期的なstart/pump/close再入を拒否する。"""

        if self._active_operation is not None:
            raise PlaybackSyncRuntimeError(f"{operation} cannot run during {self._active_operation}")
        self._active_operation = operation

    def _leave(self) -> None:
        """現在の同期operationを終了する。"""

        self._active_operation = None


def _error_info(error: BaseException) -> PlaybackSyncRuntimeErrorInfo:
    """例外をstatus用のbounded情報へ変換する。"""

    return PlaybackSyncRuntimeErrorInfo(type(error).__name__, _error_message(error))


def _claim_components(*components: object) -> None:
    """Runtimeへ移したcomponentのSession間再利用を拒否する。"""

    with _CLAIMED_COMPONENTS_LOCK:
        if any(component in _CLAIMED_COMPONENTS for component in components):
            raise PlaybackSyncRuntimeError("Playback sync component is already owned by another Runtime")
        _CLAIMED_COMPONENTS.update(components)


def _error_message(error: BaseException) -> str:
    """例外messageを安全に1024文字へ制限する。"""

    try:
        message = str(error)
    except Exception:
        message = "<unprintable exception>"
    return message[:1024]


__all__ = (
    "PlaybackSyncRuntime",
    "PlaybackSyncRuntimeError",
    "PlaybackSyncRuntimeErrorInfo",
    "PlaybackSyncRuntimeStatus",
)
