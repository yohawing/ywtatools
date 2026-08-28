"""YWTA Link共通AdapterのMain Thread dispatchを検証する。"""

from __future__ import annotations

import queue
import threading
import time
import unittest
from typing import Callable

from ywta_link import (
    AdapterDispatch,
    AdapterDispatchError,
    DispatchErrorInfo,
    Envelope,
    Frame,
)


def _frame(message_id: str) -> Frame:
    """テスト用の最小Frameを作る。"""

    return Frame(
        Envelope(
            protocol_version=1,
            message_id=message_id,
            type="publish",
            sender="blender:peer-001",
            room="shot-010",
            topic="sync/test",
        )
    )


class FakeClient:
    """receive呼出threadと有限queueを記録するfake Client。"""

    def __init__(self, frames: list[Frame] | None = None) -> None:
        """指定Frameを順に返すfakeを作る。"""

        self._frames: queue.Queue[object] = queue.Queue()
        for frame in frames or []:
            self._frames.put(frame)
        self.receive_threads: list[int] = []
        self.receive_timeouts: list[float | None] = []
        self.closed = threading.Event()

    def receive(self, timeout: float | None = None) -> Frame:
        """Frameを取り出し、close後はdisconnectを返す。"""

        self.receive_threads.append(threading.get_ident())
        self.receive_timeouts.append(timeout)
        item = self._frames.get(timeout=timeout)
        if item is _DISCONNECT:
            raise RuntimeError("closed")
        return item  # type: ignore[return-value]

    def close(self) -> None:
        """close呼出を記録する。"""

        self.closed.set()
        self._frames.put(_DISCONNECT)


_DISCONNECT = object()


class BlockingClient(FakeClient):
    """closeでreceiveのblockingを解除するfake。"""

    def __init__(self) -> None:
        """解除Eventを初期化する。"""

        super().__init__()
        self.release = threading.Event()

    def receive(self, timeout: float | None = None) -> Frame:
        """明示的なreleaseまで待つ。"""

        self.receive_threads.append(threading.get_ident())
        self.receive_timeouts.append(timeout)
        self.release.wait()
        raise RuntimeError("closed")

    def close(self) -> None:
        """closeでblocking receiveを解除する。"""

        super().close()
        self.release.set()


class BrokenCloseClient(BlockingClient):
    """closeしてもreceiveを解除せず、stop timeoutを再現するfake。"""

    def close(self) -> None:
        """close通知だけを記録する。"""

        self.closed.set()


class ErrorClient(FakeClient):
    """receiveで指定例外を返すfake。"""

    def __init__(self, error: Exception) -> None:
        """送出する例外を保存する。"""

        super().__init__()
        self.error = error

    def receive(self, timeout: float | None = None) -> Frame:
        """receiver thread上で例外を送出する。"""

        self.receive_threads.append(threading.get_ident())
        self.receive_timeouts.append(timeout)
        raise self.error


def _wait_until(predicate: Callable[[], bool], timeout: float = 1.0) -> None:
    """predicateが真になるまで短くpollする。"""

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition was not satisfied before timeout")


class AdapterDispatchTest(unittest.TestCase):
    """受信threadとHost Main Threadの境界を検証する。"""

    def test_receiver_thread_only_receives_and_main_thread_drains_in_order(self) -> None:
        """receiveはbackgroundだけ、handlerは生成元threadで順序通り呼ばれる。"""

        client = FakeClient([_frame("message-001"), _frame("message-002")])
        dispatch = AdapterDispatch(client)
        self.addCleanup(dispatch.close_session)
        owner_thread = threading.get_ident()

        self.assertTrue(dispatch.start())
        self.assertFalse(dispatch.start())
        _wait_until(lambda: dispatch.status.queue_size == 2)
        received_thread_ids = set(client.receive_threads)
        self.assertEqual(len(received_thread_ids), 1)
        self.assertNotEqual(received_thread_ids.pop(), owner_thread)
        self.assertTrue(client.receive_timeouts)
        self.assertTrue(all(timeout is None for timeout in client.receive_timeouts))

        applied: list[tuple[str, int]] = []
        self.assertEqual(dispatch.drain(lambda item: applied.append((item.envelope.message_id, threading.get_ident())), 1), 1)
        self.assertEqual(applied, [("message-001", owner_thread)])
        self.assertEqual(dispatch.drain(lambda item: applied.append((item.envelope.message_id, threading.get_ident()))), 1)
        self.assertEqual(applied, [("message-001", owner_thread), ("message-002", owner_thread)])

    def test_overflow_stops_receiver_without_dropping_queued_frames(self) -> None:
        """満杯時は古いFrameを捨てず、fail-closedでreceiverを停止する。"""

        client = FakeClient([_frame("message-001"), _frame("message-002"), _frame("message-003")])
        dispatch = AdapterDispatch(client, queue_capacity=2)
        self.addCleanup(dispatch.close_session)
        dispatch.start()
        _wait_until(lambda: dispatch.status.overflowed and not dispatch.status.running)

        status = dispatch.status
        self.assertFalse(status.running)
        self.assertEqual(status.queue_size, 2)
        self.assertIsInstance(status.receiver_error, DispatchErrorInfo)
        self.assertEqual(status.receiver_error.exception_type, "DispatchOverflowError")
        self.assertTrue(client.closed.is_set())
        delivered: list[str] = []
        self.assertEqual(dispatch.drain(lambda item: delivered.append(item.envelope.message_id)), 2)
        self.assertEqual(delivered, ["message-001", "message-002"])

    def test_stop_is_finite_and_idempotent(self) -> None:
        """close解除可能なClientではstopが完了し、clean stop後のstartを拒否する。"""

        client = BlockingClient()
        dispatch = AdapterDispatch(client, stop_timeout=0.02)
        self.addCleanup(dispatch.close_session)
        dispatch.start()
        _wait_until(lambda: bool(client.receive_threads))

        started = time.monotonic()
        self.assertTrue(dispatch.stop())
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertTrue(dispatch.stop(timeout=0.01))
        self.assertFalse(dispatch.status.running)
        self.assertFalse(dispatch.start())

    def test_stop_timeout_is_finite_when_client_close_cannot_unblock(self) -> None:
        """壊れたcloseでもstopは有限時間で戻り、解除後に完了できる。"""

        client = BrokenCloseClient()
        dispatch = AdapterDispatch(client, stop_timeout=0.02)
        dispatch.start()
        _wait_until(lambda: bool(client.receive_threads))

        started = time.monotonic()
        self.assertFalse(dispatch.stop())
        self.assertLess(time.monotonic() - started, 0.5)
        client.release.set()
        self.assertTrue(dispatch.stop(timeout=0.5))

    def test_receiver_error_is_retained_for_status_observation(self) -> None:
        """disconnect相当の例外はreceiver threadを止め、statusから観測できる。"""

        client = ErrorClient(RuntimeError("disconnected"))
        dispatch = AdapterDispatch(client)
        self.addCleanup(dispatch.close_session)
        dispatch.start()
        _wait_until(lambda: dispatch.status.receiver_error is not None)

        status = dispatch.status
        self.assertFalse(status.running)
        self.assertIsInstance(status.receiver_error, DispatchErrorInfo)
        self.assertEqual(status.receiver_error.exception_type, "RuntimeError")
        _wait_until(client.closed.is_set)
        self.assertTrue(client.closed.is_set())
        self.assertEqual(dispatch.drain(lambda _item: None), 0)
        with self.assertRaises(AdapterDispatchError):
            dispatch.start()

    def test_timeout_error_is_receiver_error_not_a_poll_timeout(self) -> None:
        """blocking receiveからのTimeoutErrorを正常poll扱いせず記録する。"""

        client = ErrorClient(TimeoutError("unexpected timeout"))
        dispatch = AdapterDispatch(client)
        self.addCleanup(dispatch.close_session)
        dispatch.start()
        _wait_until(lambda: dispatch.status.receiver_error is not None)

        self.assertIsInstance(dispatch.status.receiver_error, DispatchErrorInfo)
        self.assertEqual(dispatch.status.receiver_error.exception_type, "TimeoutError")
        self.assertEqual(len(client.receive_timeouts), 1)
        self.assertIsNone(client.receive_timeouts[0])

    def test_handler_error_isolated_until_explicit_take_failed(self) -> None:
        """Host handlerの失敗Frameを隔離し、後続処理を停止して明示回収する。"""

        client = FakeClient([_frame("message-001"), _frame("message-002"), _frame("message-003")])
        dispatch = AdapterDispatch(client, queue_capacity=3)
        self.addCleanup(dispatch.close_session)
        dispatch.start()
        _wait_until(lambda: dispatch.status.queue_size == 3)

        seen: list[str] = []

        def fail_apply(item: Frame) -> None:
            """適用失敗を再現する。"""

            seen.append(item.envelope.message_id)
            if item.envelope.message_id == "message-002":
                raise RuntimeError("apply failed")

        with self.assertRaisesRegex(RuntimeError, "apply failed"):
            dispatch.drain(fail_apply)
        self.assertEqual(seen, ["message-001", "message-002"])
        self.assertEqual(dispatch.status.queue_size, 1)
        self.assertEqual(dispatch.status.failed_count, 1)
        self.assertLessEqual(dispatch.status.queue_size + dispatch.status.failed_count, 3)
        self.assertIsInstance(dispatch.status.handler_error, DispatchErrorInfo)
        self.assertEqual(dispatch.status.handler_error.exception_type, "RuntimeError")
        self.assertEqual(dispatch.status.handler_error.message, "apply failed")

        later: list[str] = []
        self.assertEqual(dispatch.drain(lambda item: later.append(item.envelope.message_id)), 0)
        self.assertEqual(later, [])
        failed = dispatch.take_failed()
        self.assertIsNotNone(failed)
        self.assertEqual(failed.envelope.message_id, "message-002")
        self.assertEqual(dispatch.status.failed_count, 0)
        self.assertEqual(dispatch.drain(lambda item: later.append(item.envelope.message_id)), 1)
        self.assertEqual(later, ["message-003"])

    def test_drain_is_owner_thread_only_and_close_session_discards_pending(self) -> None:
        """Main Thread以外のdrainを拒否し、Session closeでpendingを破棄する。"""

        client = FakeClient([_frame("message-001")])
        dispatch = AdapterDispatch(client)
        dispatch.start()
        _wait_until(lambda: dispatch.status.queue_size == 1)
        failures: list[BaseException] = []

        def drain_from_worker() -> None:
            try:
                dispatch.drain(lambda _item: None)
            except BaseException as exc:
                failures.append(exc)

        worker = threading.Thread(target=drain_from_worker)
        worker.start()
        worker.join(timeout=1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(failures), 1)
        self.assertIsInstance(failures[0], AdapterDispatchError)

        def fail_apply(_item: Frame) -> None:
            """Session close前のfailed slotを作る。"""

            raise RuntimeError("apply failed")

        with self.assertRaises(RuntimeError):
            dispatch.drain(fail_apply)
        self.assertEqual(dispatch.status.failed_count, 1)
        self.assertTrue(dispatch.close_session())
        self.assertTrue(dispatch.status.closed)
        self.assertEqual(dispatch.status.queue_size, 0)
        self.assertEqual(dispatch.status.failed_count, 0)
        self.assertIsNone(dispatch.take_failed())
        with self.assertRaises(AdapterDispatchError):
            dispatch.start()


if __name__ == "__main__":
    unittest.main()
