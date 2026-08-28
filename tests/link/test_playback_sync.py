"""Playback同期runtimeのlifecycleとMain Thread境界を検証する。"""

from __future__ import annotations

import queue
import threading
import time
import unittest
from typing import Callable

from ywta_link import (
    AdapterDispatch,
    AuthorityHandoffTracker,
    AuthorityHandoffTransport,
    Envelope,
    Frame,
    Playback,
    PlaybackController,
    PlaybackSyncRuntime,
    PlaybackSyncRuntimeError,
    PlaybackTopicTransport,
    PlaybackTimeMapper,
    RationalRate,
    Time,
)


class _Client:
    """実Clientの最小transport/dispatch代替。"""

    def __init__(self) -> None:
        self.peer_id = "peer-local"
        self.fail_unsubscribe = False
        self.subscriptions: list[tuple[str, str]] = []
        self.unsubscriptions: list[tuple[str, str]] = []
        self.closed = threading.Event()
        self.frames: queue.Queue[Frame] = queue.Queue()
        self.receive_error: Exception | None = None

    def subscribe(self, room: str, topic: str) -> str:
        """購読を記録する。"""

        self.subscriptions.append((room, topic))
        return "subscription-001"

    def unsubscribe(self, room: str, topic: str) -> str:
        """購読解除を記録する。"""

        if self.fail_unsubscribe:
            raise RuntimeError("unsubscribe failed")
        self.unsubscriptions.append((room, topic))
        return "unsubscription-001"

    def publish(self, room: str, **kwargs: object) -> str:
        """publishの戻り値を提供する。"""

        return "message-001"

    def request(self, room: str, target: str, **kwargs: object) -> str:
        """Authority requestの戻り値を提供する。"""

        return kwargs.get("message_id", "request-001")  # type: ignore[return-value]

    def response(self, room: str, target: str, correlation_id: str, **kwargs: object) -> str:
        """Authority responseの戻り値を提供する。"""

        return "response-001"

    def receive(self, timeout: float | None = None) -> Frame:
        """停止通知まで受信queueを待つ。"""

        if self.receive_error is not None:
            raise self.receive_error
        while not self.closed.is_set():
            try:
                return self.frames.get(timeout=0.01)
            except queue.Empty:
                continue
        raise RuntimeError("client closed")

    def close(self) -> None:
        """受信threadを解除する。"""

        self.closed.set()


def _playback() -> Playback:
    """テスト用Playbackを返す。"""

    rate = RationalRate(24, 1)
    return Playback(
        state="paused",
        position=Time(12, None, None, rate),
        playback_range=Time(None, 0, 24, rate),
        speed=1.0,
        direction="forward",
        loop_mode="once",
        change_id="change-001",
    )


def _frame(message_id: str, *, room: str = "room", topic: str = "topic", schema: str | None = None) -> Frame:
    """テスト用Frameを返す。"""

    return Frame(
        Envelope(
            protocol_version=1,
            message_id=message_id,
            type="publish",
            sender="peer-remote",
            room=room,
            target=None,
            topic=topic,
            correlation_id=None,
            schema="ywta.common.playback.v1" if schema is None else schema,
            body=_playback().to_dict(),
        )
    )


def _controller() -> PlaybackController:
    """テスト用Controllerを返す。"""

    mapper = PlaybackTimeMapper(
        ticks_per_host_unit=1,
        host_unit_rate=RationalRate(24, 1),
        time_unit="frames",
    )
    return PlaybackController(
        "peer-local",
        "timeline",
        mapper,
        lambda _channel: "peer-remote",
        lambda _playback: None,
        lambda _snapshot: None,
    )


class PlaybackSyncRuntimeTest(unittest.TestCase):
    """PlaybackSyncRuntimeの責務を検証する。"""

    def _runtime(
        self,
    ) -> tuple[
        PlaybackSyncRuntime,
        _Client,
        AdapterDispatch,
        AuthorityHandoffTransport,
        PlaybackTopicTransport,
        PlaybackController,
    ]:
        """実componentを使ったruntimeを作る。"""

        client = _Client()
        dispatch = AdapterDispatch(client)
        authority_tracker = AuthorityHandoffTracker({"timeline": "peer-remote"}, session_id="session-001")
        authority_transport = AuthorityHandoffTransport(client, "room", authority_tracker)
        transport = PlaybackTopicTransport(client, "room", "topic")
        controller = _controller()
        runtime = PlaybackSyncRuntime(dispatch, authority_transport, transport, controller)
        return runtime, client, dispatch, authority_transport, transport, controller

    @staticmethod
    def _replace(component: object, name: str, function: Callable[..., object]) -> None:
        """テスト対象componentの一つの動作だけを差し替える。"""

        setattr(component, name, function)

    def test_start_order_and_idempotence(self) -> None:
        """subscribeがdispatch.startより先で、再startは無操作になる。"""

        runtime, _client, dispatch, authority, transport, controller = self._runtime()
        self.addCleanup(controller.close)
        calls: list[str] = []
        self._replace(authority, "subscribe", lambda: calls.append("authority.subscribe") or True)
        self._replace(transport, "subscribe", lambda: calls.append("playback.subscribe") or True)
        self._replace(dispatch, "start", lambda: calls.append("start") or True)
        self._replace(authority, "close", lambda: calls.append("authority.close") or True)
        self._replace(transport, "close", lambda: calls.append("transport.close") or True)

        self.assertTrue(runtime.start())
        self.assertFalse(runtime.start())
        self.assertEqual(calls, ["authority.subscribe", "playback.subscribe", "start"])
        self.assertTrue(runtime.status.started)
        self.assertFalse(runtime.status.failed)
        runtime.close()

    def test_start_failure_rolls_back_and_cannot_restart(self) -> None:
        """dispatch起動失敗時は全componentを閉じ、receiverを残さない。"""

        runtime, _client, dispatch, authority, transport, controller = self._runtime()
        self.addCleanup(controller.close)
        calls: list[str] = []
        self._replace(authority, "subscribe", lambda: calls.append("authority.subscribe") or True)
        self._replace(transport, "subscribe", lambda: calls.append("playback.subscribe") or True)
        self._replace(dispatch, "start", lambda: calls.append("start") or False)
        self._replace(authority, "close", lambda: calls.append("authority.close") or True)
        self._replace(transport, "close", lambda: calls.append("rollback") or True)
        self._replace(dispatch, "close_session", lambda: calls.append("dispatch.close") or True)
        self._replace(controller, "close", lambda: calls.append("controller.close") or True)

        with self.assertRaises(PlaybackSyncRuntimeError):
            runtime.start()
        self.assertEqual(
            calls,
            [
                "authority.subscribe",
                "playback.subscribe",
                "start",
                "authority.close",
                "rollback",
                "dispatch.close",
                "controller.close",
            ],
        )
        self.assertTrue(runtime.status.failed)
        self.assertTrue(runtime.status.closed)
        self.assertFalse(runtime.status.started)
        with self.assertRaises(PlaybackSyncRuntimeError):
            runtime.start()

    def test_subscribe_false_rolls_back_without_starting_dispatch(self) -> None:
        """既に購読済み等のFalseを成功扱いせず全componentを閉じる。"""

        runtime, _client, dispatch, authority, transport, controller = self._runtime()
        calls: list[str] = []
        self._replace(authority, "subscribe", lambda: calls.append("authority.subscribe") or True)
        self._replace(authority, "close", lambda: calls.append("authority.close") or True)
        self._replace(transport, "subscribe", lambda: calls.append("subscribe") or False)
        self._replace(dispatch, "start", lambda: calls.append("start") or True)
        self._replace(transport, "close", lambda: calls.append("transport.close") or True)
        self._replace(dispatch, "close_session", lambda: calls.append("dispatch.close") or True)
        self._replace(controller, "close", lambda: calls.append("controller.close") or True)

        with self.assertRaises(PlaybackSyncRuntimeError):
            runtime.start()
        self.assertEqual(
            calls,
            ["authority.subscribe", "subscribe", "authority.close", "transport.close", "dispatch.close", "controller.close"],
        )
        self.assertTrue(runtime.status.closed)
        self.assertTrue(runtime.status.failed)

    def test_start_rollback_failure_remains_open_for_close_retry(self) -> None:
        """unsubscribe rollback失敗時はClientを閉じずclose再試行を許可する。"""

        runtime, _client, dispatch, authority, transport, controller = self._runtime()
        calls: list[str] = []
        rollback_fails = [True]
        self._replace(authority, "subscribe", lambda: calls.append("authority.subscribe") or True)
        self._replace(transport, "subscribe", lambda: calls.append("playback.subscribe") or True)
        self._replace(dispatch, "start", lambda: False)

        def close_transport() -> bool:
            calls.append("transport.close")
            if rollback_fails[0]:
                raise RuntimeError("unsubscribe failed")
            return True

        self._replace(authority, "close", lambda: calls.append("authority.close") or True)
        self._replace(transport, "close", close_transport)
        self._replace(dispatch, "close_session", lambda: calls.append("dispatch.close") or True)
        self._replace(controller, "close", lambda: calls.append("controller.close") or True)

        with self.assertRaises(PlaybackSyncRuntimeError):
            runtime.start()
        self.assertEqual(["authority.subscribe", "playback.subscribe", "authority.close", "transport.close"], calls)
        self.assertTrue(runtime.status.failed)
        self.assertFalse(runtime.status.closed)

        rollback_fails[0] = False
        self.assertTrue(runtime.close())
        self.assertEqual(
            [
                "authority.subscribe",
                "playback.subscribe",
                "authority.close",
                "transport.close",
                "authority.close",
                "transport.close",
                "dispatch.close",
                "controller.close",
            ],
            calls,
        )
        self.assertTrue(runtime.status.closed)

    def test_pump_counts_valid_and_unrelated_frames(self) -> None:
        """関連Frameと無関係Frameの両方をdrain件数へ含める。"""

        runtime, _client, dispatch, authority, transport, controller = self._runtime()
        self.addCleanup(controller.close)
        self._replace(dispatch, "start", lambda: True)
        self._replace(transport, "subscribe", lambda: True)
        self._replace(transport, "close", lambda: True)
        seen: list[str] = []

        def drain(handler: Callable[[Frame], None], max_items: int | None = None) -> int:
            """二つのFrameをhandlerへ渡す。"""

            frames = [_frame("valid"), _frame("unrelated", room="other")]
            if max_items is not None:
                frames = frames[:max_items]
            for item in frames:
                handler(item)
                seen.append(item.envelope.message_id)
            return len(frames)

        self._replace(dispatch, "drain", drain)
        self._replace(transport, "handle_frame", lambda frame, _controller: frame.envelope.room == "room")
        runtime.start()
        self.assertEqual(runtime.pump(), 2)
        self.assertEqual(seen, ["valid", "unrelated"])
        runtime.close()

    def test_pump_routes_each_frame_to_authority_before_playback(self) -> None:
        """各FrameをAuthorityへ先に渡し、未処理だけPlaybackへ渡す。"""

        runtime, _client, dispatch, authority, transport, controller = self._runtime()
        events: list[tuple[str, str]] = []
        self._replace(authority, "subscribe", lambda: True)
        self._replace(transport, "subscribe", lambda: True)
        self._replace(dispatch, "start", lambda: True)
        self._replace(
            authority,
            "handle_frame",
            lambda frame: events.append(("authority", frame.envelope.message_id)) or frame.envelope.message_id == "control",
        )
        self._replace(
            transport,
            "handle_frame",
            lambda frame, _controller: events.append(("playback", frame.envelope.message_id)) or True,
        )

        def drain(handler: Callable[[Frame], None], max_items: int | None = None) -> int:
            """controlとPlaybackの二つのFrameを順序どおり渡す。"""

            frames = [_frame("control"), _frame("playback")]
            if max_items is not None:
                frames = frames[:max_items]
            for frame in frames:
                handler(frame)
            return len(frames)

        self._replace(dispatch, "drain", drain)
        runtime.start()
        self.assertEqual(runtime.pump(), 2)
        self.assertEqual(
            events,
            [("authority", "control"), ("authority", "playback"), ("playback", "playback")],
        )
        runtime.close()

    def test_handler_error_marks_failed_and_adapter_keeps_failed_frame(self) -> None:
        """handler失敗を型付けし、Adapterのfailed slotを保持する。"""

        runtime, _client, dispatch, authority, transport, controller = self._runtime()
        self.addCleanup(controller.close)
        self._replace(transport, "subscribe", lambda: True)
        self._replace(dispatch, "start", lambda: True)
        runtime.start()
        with dispatch._lock:  # type: ignore[attr-defined]
            dispatch._queue.append(_frame("failed"))  # type: ignore[attr-defined]
        self._replace(
            transport, "handle_frame", lambda _frame, _controller: (_ for _ in ()).throw(RuntimeError("apply failed"))
        )

        with self.assertRaises(PlaybackSyncRuntimeError) as raised:
            runtime.pump()
        self.assertIsInstance(raised.exception.__cause__, RuntimeError)
        self.assertTrue(runtime.status.failed)
        self.assertEqual(runtime.status.error.exception_type, "RuntimeError")  # type: ignore[union-attr]
        self.assertEqual(dispatch.status.failed_count, 1)
        self.assertEqual(dispatch.take_failed().envelope.message_id, "failed")  # type: ignore[union-attr]
        with self.assertRaises(PlaybackSyncRuntimeError):
            runtime.pump()
        runtime.close()

    def test_receiver_error_is_promoted_from_background_dispatch(self) -> None:
        """receiver停止をdrain 0件の正常idleと誤認しない。"""

        runtime, client, dispatch, _authority, _transport, _controller = self._runtime()
        client.receive_error = RuntimeError("receiver disconnected")
        runtime.start()
        deadline = time.monotonic() + 1.0
        while dispatch.status.receiver_error is None and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertIsNotNone(dispatch.status.receiver_error)

        with self.assertRaisesRegex(PlaybackSyncRuntimeError, "receiver disconnected"):
            runtime.pump()
        self.assertTrue(runtime.status.failed)
        self.assertEqual("RuntimeError", runtime.status.error.exception_type)  # type: ignore[union-attr]
        runtime.close()

    def test_close_order_and_idempotence(self) -> None:
        """closeはtransport、dispatch、controller順で一度だけ行う。"""

        runtime, _client, dispatch, authority, transport, controller = self._runtime()
        calls: list[str] = []
        self._replace(authority, "close", lambda: calls.append("authority") or True)
        self._replace(transport, "close", lambda: calls.append("transport") or True)
        self._replace(dispatch, "close_session", lambda: calls.append("dispatch") or True)
        self._replace(controller, "close", lambda: calls.append("controller") or True)

        self.assertTrue(runtime.close())
        self.assertFalse(runtime.close())
        self.assertEqual(calls, ["authority", "transport", "dispatch", "controller"])
        self.assertTrue(runtime.status.closed)
        self.assertFalse(runtime.status.failed)

    def test_unsubscribe_retry_keeps_dispatch_and_controller_running(self) -> None:
        """unsubscribe失敗時は後続componentを止めず、次回closeで再試行する。"""

        runtime, client, dispatch, authority, transport, controller = self._runtime()
        calls: list[str] = []
        self._replace(dispatch, "start", lambda: calls.append("start") or True)
        self._replace(dispatch, "close_session", lambda: calls.append("dispatch") or True)
        self._replace(controller, "close", lambda: calls.append("controller") or True)
        runtime.start()
        client.fail_unsubscribe = True

        with self.assertRaises(PlaybackSyncRuntimeError):
            runtime.close()
        self.assertFalse(runtime.status.closed)
        self.assertFalse(runtime.status.failed)
        self.assertEqual(calls, ["start"])
        client.fail_unsubscribe = False
        self.assertTrue(runtime.close())
        self.assertEqual(calls, ["start", "dispatch", "controller"])

    def test_close_attempts_controller_after_dispatch_error_and_aggregates_failure(self) -> None:
        """dispatch終了失敗後もControllerを閉じ、RuntimeをFailedにする。"""

        runtime, _client, dispatch, authority, transport, controller = self._runtime()
        calls: list[str] = []
        self._replace(authority, "close", lambda: calls.append("authority") or True)
        self._replace(transport, "close", lambda: calls.append("transport") or True)
        self._replace(dispatch, "close_session", lambda: calls.append("dispatch") or False)

        def fail_controller() -> bool:
            """Controller終了失敗を再現する。"""

            calls.append("controller")
            raise RuntimeError("controller close failed")

        self._replace(controller, "close", fail_controller)
        with self.assertRaises(PlaybackSyncRuntimeError):
            runtime.close()
        self.assertEqual(calls, ["authority", "transport", "dispatch", "controller"])
        self.assertTrue(runtime.status.closed)
        self.assertTrue(runtime.status.failed)

    def test_close_before_start_closes_all_components(self) -> None:
        """未startでも四componentを安全に終了する。"""

        runtime, _client, dispatch, authority, transport, controller = self._runtime()
        calls: list[str] = []
        self._replace(authority, "close", lambda: calls.append("authority") or True)
        self._replace(transport, "close", lambda: calls.append("transport") or True)
        self._replace(dispatch, "close_session", lambda: calls.append("dispatch") or True)
        self._replace(controller, "close", lambda: calls.append("controller") or True)

        self.assertTrue(runtime.close())
        self.assertEqual(calls, ["authority", "transport", "dispatch", "controller"])
        self.assertFalse(runtime.status.started)

    def test_components_cannot_be_reused_by_another_runtime(self) -> None:
        """移譲componentの同時利用とclose後の再利用を拒否する。"""

        runtime, _client, dispatch, authority, transport, controller = self._runtime()
        for closed in (False, True):
            if closed:
                runtime.close()
            with self.assertRaisesRegex(PlaybackSyncRuntimeError, "already owned"):
                PlaybackSyncRuntime(dispatch, authority, transport, controller)

    def test_dispatch_and_transport_must_share_client_identity(self) -> None:
        """subscribe/publishとreceiveを別Clientへ分離させない。"""

        receive_client = _Client()
        transport_client = _Client()
        dispatch = AdapterDispatch(receive_client)
        authority_tracker = AuthorityHandoffTracker({"timeline": "peer-remote"}, session_id="session-001")
        authority = AuthorityHandoffTransport(transport_client, "room", authority_tracker)
        transport = PlaybackTopicTransport(transport_client, "room", "topic")
        controller = _controller()
        self.addCleanup(dispatch.close_session)
        self.addCleanup(authority.close)
        self.addCleanup(transport.close)
        self.addCleanup(controller.close)

        with self.assertRaisesRegex(PlaybackSyncRuntimeError, "same Client instance"):
            PlaybackSyncRuntime(dispatch, authority, transport, controller)

    def test_owner_thread_and_reentry_boundaries(self) -> None:
        """owner以外と同期再入を明示的に拒否する。"""

        runtime, _client, dispatch, authority, transport, controller = self._runtime()
        self.addCleanup(controller.close)
        self._replace(transport, "subscribe", lambda: True)
        self._replace(dispatch, "start", lambda: True)
        runtime.start()
        errors: list[BaseException] = []

        def call_from_worker() -> None:
            """owner外の操作を試行する。"""

            for operation in (runtime.pump, runtime.close):
                try:
                    operation()
                except BaseException as error:
                    errors.append(error)

        worker = threading.Thread(target=call_from_worker)
        worker.start()
        worker.join(timeout=1)
        self.assertFalse(worker.is_alive())
        self.assertEqual([type(error) for error in errors], [PlaybackSyncRuntimeError] * 2)

        # 既にstartedのruntimeではsubscribeへ到達しないため、独立runtimeで確認する。
        runtime.close()
        second, _client2, dispatch2, authority2, transport2, controller2 = self._runtime()
        self.addCleanup(controller2.close)

        def reenter() -> bool:
            """subscribe中のstart再入を再現する。"""

            second.start()
            return True

        self._replace(transport2, "subscribe", reenter)
        self._replace(dispatch2, "start", lambda: True)
        with self.assertRaises(PlaybackSyncRuntimeError):
            second.start()
        self.assertTrue(second.status.failed)

    def test_post_close_and_failed_operations_fail_closed(self) -> None:
        """close後・Failed後のstart/pumpを拒否する。"""

        runtime, _client, dispatch, authority, transport, controller = self._runtime()
        self._replace(authority, "close", lambda: True)
        self._replace(transport, "close", lambda: True)
        self._replace(dispatch, "close_session", lambda: True)
        self._replace(controller, "close", lambda: True)
        runtime.close()
        with self.assertRaises(PlaybackSyncRuntimeError):
            runtime.start()
        with self.assertRaises(PlaybackSyncRuntimeError):
            runtime.pump()

        failed, _client2, dispatch2, authority2, transport2, controller2 = self._runtime()
        self.addCleanup(controller2.close)
        self._replace(transport2, "subscribe", lambda: True)
        self._replace(authority2, "subscribe", lambda: True)
        self._replace(dispatch2, "start", lambda: False)
        self._replace(authority2, "close", lambda: True)
        self._replace(transport2, "close", lambda: True)
        self._replace(dispatch2, "close_session", lambda: True)
        self._replace(controller2, "close", lambda: True)
        with self.assertRaises(PlaybackSyncRuntimeError):
            failed.start()
        with self.assertRaises(PlaybackSyncRuntimeError):
            failed.pump()


if __name__ == "__main__":
    unittest.main()
