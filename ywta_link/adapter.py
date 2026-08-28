"""YWTA Link受信FrameをHost Main Threadへ渡す共通Adapter基盤。"""

from __future__ import annotations

import math
import threading
from collections import deque
from dataclasses import dataclass
from typing import Callable

from .frame import Frame


class AdapterDispatchError(RuntimeError):
    """Adapter dispatchの設定または状態が不正であることを表す。"""


class DispatchOverflowError(AdapterDispatchError):
    """受信queueが満杯になり、fail-closedで受信を停止したことを表す。"""


@dataclass(frozen=True)
class DispatchErrorInfo:
    """dispatch失敗の型名と短いmessageだけを保持する。"""

    exception_type: str
    message: str


# 既存のhandler error向け名称を互換の型aliasとして残す。
HandlerErrorInfo = DispatchErrorInfo


@dataclass(frozen=True)
class DispatchStatus:
    """Adapter受信dispatchの観測可能なsnapshot。"""

    started: bool
    running: bool
    closed: bool
    queue_size: int
    queue_capacity: int
    receiver_error: DispatchErrorInfo | None
    handler_error: DispatchErrorInfo | None
    failed_count: int
    overflowed: bool


FrameHandler = Callable[[Frame], None]


class AdapterDispatch:
    """LinkClientの受信だけをbackground threadで行い、Frameを明示drainする。"""

    def __init__(
        self,
        client: object,
        *,
        queue_capacity: int = 256,
        stop_timeout: float = 1.0,
    ) -> None:
        """有限queueと有限timeoutを検証してAdapterを初期化する。

        `client.receive`はこのAdapterが作るreceiver threadからだけ呼び出す。
        `drain`のhandlerはAdapter生成元のthreadでのみ実行する。
        """

        receive = getattr(client, "receive", None)
        if not callable(receive):
            raise AdapterDispatchError("client must provide a callable receive method")
        if isinstance(queue_capacity, bool) or not isinstance(queue_capacity, int) or queue_capacity <= 0:
            raise AdapterDispatchError("queue_capacity must be a positive integer")
        _non_negative_finite(stop_timeout, "stop_timeout")

        self._client = client
        self._receive = receive
        self._queue_capacity = queue_capacity
        self._stop_timeout = float(stop_timeout)
        self._owner_thread_id = threading.get_ident()
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._queue: deque[Frame] = deque()
        self._failed: deque[Frame] = deque()
        self._reserved = 0
        self._thread: threading.Thread | None = None
        self._started = False
        self._running = False
        self._closed = False
        self._receiver_error: DispatchErrorInfo | None = None
        self._handler_error: DispatchErrorInfo | None = None
        self._overflowed = False

    def start(self) -> bool:
        """receiverを一度だけ起動する。起動済みなら何もせずFalseを返す。"""

        with self._lock:
            if self._closed:
                raise AdapterDispatchError("dispatch is closed")
            if self._receiver_error is not None:
                raise AdapterDispatchError("dispatch cannot restart after receiver error")
            if self._started:
                return False
            self._stop_event.clear()
            self._started = True
            self._running = True
            receiver = threading.Thread(
                target=self._receive_loop,
                name="ywta-link-receiver",
                daemon=True,
            )
            self._thread = receiver
            receiver.start()
            return True

    def stop(self, timeout: float | None = None) -> bool:
        """receiverへ停止を通知し、有限時間だけjoinする。

        戻り値はtimeout内にreceiverが終了したかを示す。receiverが終了しない場合も
        呼び出し元を無期限に待たせず、`status.running`から状態を観測できる。
        """

        if timeout is None:
            timeout = self._stop_timeout
        else:
            _non_negative_finite(timeout, "timeout")

        with self._lock:
            thread = self._thread
            if thread is None or not self._running:
                return True
            self._stop_event.set()

        self._close_client()
        if thread is threading.current_thread():
            return False
        thread.join(float(timeout))
        return not thread.is_alive()

    def close_session(self, timeout: float | None = None) -> bool:
        """Sessionを閉じ、停止後に未dispatchのFrameを破棄する。"""

        stopped = self.stop(timeout)
        with self._lock:
            self._closed = True
            self._queue.clear()
            self._failed.clear()
        return stopped

    def drain(self, handler: FrameHandler, max_items: int | None = None) -> int:
        """Main Thread上でqueueを順序どおり適用し、処理件数を返す。

        handlerが例外を送出した場合は対象Frameをfailed slotへ隔離して例外を再送出する。
        そのdrainの後続Frameは処理せず、`take_failed`による明示回収まで再適用しない。
        """

        if threading.get_ident() != self._owner_thread_id:
            raise AdapterDispatchError("drain must run on the Adapter owner thread")
        if not callable(handler):
            raise AdapterDispatchError("handler must be callable")
        if max_items is not None and (isinstance(max_items, bool) or not isinstance(max_items, int) or max_items < 0):
            raise AdapterDispatchError("max_items must be a non-negative integer or None")

        processed = 0
        while max_items is None or processed < max_items:
            with self._lock:
                if self._closed or self._failed or not self._queue:
                    return processed
                frame = self._queue.popleft()
                self._reserved += 1
            try:
                handler(frame)
            except BaseException as exc:
                with self._lock:
                    self._reserved -= 1
                    if not self._closed:
                        self._failed.append(frame)
                        self._handler_error = _dispatch_error_info(exc)
                raise
            else:
                with self._lock:
                    self._reserved -= 1
                processed += 1
        return processed

    @property
    def status(self) -> DispatchStatus:
        """receiver、queue、errorの現時点snapshotを返す。"""

        with self._lock:
            return DispatchStatus(
                started=self._started,
                running=self._running,
                closed=self._closed,
                queue_size=len(self._queue),
                queue_capacity=self._queue_capacity,
                receiver_error=self._receiver_error,
                handler_error=self._handler_error,
                failed_count=len(self._failed),
                overflowed=self._overflowed,
            )

    @property
    def client(self) -> object:
        """受信に使用する借用Clientをidentity確認用に返す。"""

        return self._client

    def take_failed(self) -> Frame | None:
        """Main Thread上でfailed slotのFrameを一件だけ明示回収する。"""

        if threading.get_ident() != self._owner_thread_id:
            raise AdapterDispatchError("take_failed must run on the Adapter owner thread")
        with self._lock:
            if self._closed or not self._failed:
                return None
            return self._failed.popleft()

    def clear_pending(self) -> int:
        """未dispatchのFrameを破棄し、破棄件数を返す。"""

        with self._lock:
            discarded = len(self._queue)
            self._queue.clear()
            return discarded

    def _receive_loop(self) -> None:
        """receiver threadからだけtimeoutなしのClient receiveを呼び出すloop。"""

        try:
            while not self._stop_event.is_set():
                try:
                    frame = self._receive(timeout=None)
                except Exception as exc:
                    with self._lock:
                        if not self._stop_event.is_set():
                            self._receiver_error = _dispatch_error_info(exc)
                    return
                if not isinstance(frame, Frame):
                    with self._lock:
                        self._receiver_error = _dispatch_error_info(
                            AdapterDispatchError("client.receive must return a Frame")
                        )
                    return
                with self._lock:
                    if self._stop_event.is_set() or self._closed:
                        return
                    if len(self._queue) + len(self._failed) + self._reserved >= self._queue_capacity:
                        self._overflowed = True
                        self._receiver_error = _dispatch_error_info(DispatchOverflowError("receive queue capacity exceeded"))
                        self._stop_event.set()
                        return
                    self._queue.append(frame)
        finally:
            with self._lock:
                should_close = self._overflowed or (
                    self._receiver_error is not None and not self._stop_event.is_set()
                )
            if should_close:
                self._close_client()
            with self._lock:
                self._running = False

    def _close_client(self) -> None:
        """Clientを持つ実装だけを安全にcloseする。"""

        close = getattr(self._client, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                # 停止処理中のclose失敗は、receiverの主エラーを隠さない。
                pass


def _dispatch_error_info(error: BaseException) -> DispatchErrorInfo:
    """例外本体を保持せず、型名と上限付きmessageだけをsnapshot化する。"""

    try:
        message = str(error)
    except Exception:
        message = "<unprintable exception>"
    if len(message) > 1024:
        message = message[:1024]
    return DispatchErrorInfo(type(error).__name__, message)


def _non_negative_finite(value: object, field_name: str) -> None:
    """0以上の有限数だけを停止timeoutとして受理する。"""

    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or value < 0:
        raise AdapterDispatchError(f"{field_name} must be a non-negative finite number")


__all__ = (
    "AdapterDispatch",
    "AdapterDispatchError",
    "DispatchErrorInfo",
    "DispatchOverflowError",
    "DispatchStatus",
    "HandlerErrorInfo",
)
