"""Playback Topic TransportのClient、Frame、Controller境界を検証する。"""

from __future__ import annotations

import gc
import threading
import unittest
import weakref

from ywta_link import (
    Envelope,
    Frame,
    Playback,
    PlaybackController,
    PlaybackHostSnapshot,
    PlaybackTimeMapper,
    PlaybackTopicTransport,
    PlaybackTransportError,
    PlaybackTransportThreadError,
    RationalRate,
    Time,
)


class _FakeClient:
    """Transportの呼び出しと失敗を記録するClient代替。"""

    def __init__(self) -> None:
        self.subscribe_calls: list[tuple[str, str]] = []
        self.unsubscribe_calls: list[tuple[str, str]] = []
        self.publish_calls: list[tuple[str, dict[str, object]]] = []
        self.publish_result: object = "message-001"
        self.fail_subscribe = False
        self.fail_unsubscribe = False
        self.fail_publish = False
        self.close_calls = 0

    def subscribe(self, room: str, topic: str) -> str:
        """購読呼び出しを記録する。"""

        if self.fail_subscribe:
            raise RuntimeError("subscribe failed")
        self.subscribe_calls.append((room, topic))
        return "subscribe-001"

    def unsubscribe(self, room: str, topic: str) -> str:
        """解除呼び出しを記録する。"""

        if self.fail_unsubscribe:
            raise RuntimeError("unsubscribe failed")
        self.unsubscribe_calls.append((room, topic))
        return "unsubscribe-001"

    def publish(self, room: str, **kwargs: object) -> object:
        """Publishの引数を記録する。"""

        if self.fail_publish:
            raise RuntimeError("publish failed")
        self.publish_calls.append((room, dict(kwargs)))
        return self.publish_result

    def close(self) -> None:
        """借用Clientがcloseされていないことを検証するための記録。"""

        self.close_calls += 1


def _playback(change_id: str = "change-001") -> Playback:
    """テスト用のPlaybackを返す。"""

    timebase = RationalRate(24, 1)
    return Playback(
        state="paused",
        position=Time(12, None, None, timebase),
        playback_range=Time(None, 0, 24, timebase),
        speed=1.0,
        direction="forward",
        loop_mode="once",
        change_id=change_id,
    )


def _mapper() -> PlaybackTimeMapper:
    """テスト用のframes mapperを返す。"""

    return PlaybackTimeMapper(ticks_per_host_unit=1, host_unit_rate=RationalRate(24, 1), time_unit="frames")


def _controller(peer_id: str = "maya:peer-001", authority: str = "blender:peer-001") -> PlaybackController:
    """テスト用のControllerを返す。"""

    return PlaybackController(
        peer_id,
        "timeline",
        _mapper(),
        lambda _channel: authority,
        lambda _playback: None,
        lambda _snapshot: None,
    )


def _frame(
    *,
    room: str = "shot-010",
    topic: str = "sync/timeline/playback",
    sender: str = "blender:peer-001",
    schema: str | None = "ywta.common.playback.v1",
    body: object = None,
    raw_body: bytes = b"",
    message_id: str = "transport-001",
    message_type: str = "publish",
) -> Frame:
    """テスト用のFrameを返す。"""

    if body is None and message_type == "publish" and schema == "ywta.common.playback.v1":
        body = _playback().to_dict()
    target = "maya:peer-001" if message_type in {"request", "response", "error"} else None
    correlation_id = "request-001" if message_type in {"response", "error"} else None
    return Frame(
        Envelope(
            protocol_version=1,
            message_id=message_id,
            type=message_type,
            sender=sender,
            room=room,
            target=target,
            topic=topic if message_type == "publish" else None,
            correlation_id=correlation_id,
            schema=schema,
            body=body,
        ),
        raw_body,
    )


class PlaybackTopicTransportTest(unittest.TestCase):
    """Playback transportのlifecycleとfail-closed境界を検証する。"""

    def setUp(self) -> None:
        """各テストへ独立したClientとTransportを用意する。"""

        self.client = _FakeClient()
        self.transport = PlaybackTopicTransport(self.client, "shot-010", "sync/timeline/playback")

    def tearDown(self) -> None:
        """未終了のtransportをテスト終了時に安全に閉じる。"""

        if not self.transport.closed:
            self.transport.close()

    def test_subscribe_is_idempotent_and_active_only_after_success(self) -> None:
        """subscribe成功後だけactiveになり、二度目はClientを呼ばない。"""

        self.assertTrue(self.transport.subscribe())
        self.assertFalse(self.transport.subscribe())
        self.assertTrue(self.transport.active)
        self.assertEqual(self.client.subscribe_calls, [("shot-010", "sync/timeline/playback")])

        failed_client = _FakeClient()
        failed_client.fail_subscribe = True
        failed_transport = PlaybackTopicTransport(failed_client, "room", "topic")
        with self.assertRaises(PlaybackTransportError):
            failed_transport.subscribe()
        self.assertFalse(failed_transport.active)
        failed_client.fail_subscribe = False
        self.assertTrue(failed_transport.subscribe())
        failed_transport.close()

    def test_publish_uses_playback_schema_and_object_body(self) -> None:
        """publishがbound routingとPlayback schema/bodyをClientへ渡す。"""

        self.transport.subscribe()
        playback = _playback()

        self.assertEqual(self.transport.publish(playback), "message-001")
        self.assertEqual(
            self.client.publish_calls,
            [
                (
                    "shot-010",
                    {
                        "topic": "sync/timeline/playback",
                        "schema": "ywta.common.playback.v1",
                        "body": playback.to_dict(),
                    },
                )
            ],
        )

    def test_publish_requires_active_exact_playback_and_nonempty_message_id(self) -> None:
        """未購読、派生Playback、空Message IDを受理しない。"""

        with self.assertRaises(PlaybackTransportError):
            self.transport.publish(_playback())
        self.transport.subscribe()

        class DerivedPlayback(Playback):
            """厳密型検証用の派生型。"""

        with self.assertRaises(PlaybackTransportError):
            self.transport.publish(DerivedPlayback(**_playback().to_dict()))
        for result in ("", None, 1):
            with self.subTest(result=result):
                self.client.publish_result = result
                with self.assertRaises(PlaybackTransportError):
                    self.transport.publish(_playback())

    def test_publish_failure_is_typed(self) -> None:
        """Client publish失敗をTransportErrorへ変換する。"""

        self.transport.subscribe()
        self.client.fail_publish = True
        with self.assertRaisesRegex(PlaybackTransportError, "publish failed"):
            self.transport.publish(_playback())
        self.assertTrue(self.transport.active)

    def test_unrelated_frames_are_ignored(self) -> None:
        """異なるtype、Room、TopicはControllerへ渡さずFalseを返す。"""

        self.transport.subscribe()
        controller = _controller()
        unrelated = (
            _frame(message_type="request"),
            _frame(room="other-room"),
            _frame(topic="other-topic"),
        )
        for frame in unrelated:
            with self.subTest(frame=frame.envelope.type, room=frame.envelope.room, topic=frame.envelope.topic):
                self.assertFalse(self.transport.handle_frame(frame, controller))

    def test_valid_frame_routes_sender_and_playback_to_controller(self) -> None:
        """validなFrameをsender originのままControllerへ適用する。"""

        self.transport.subscribe()
        applied: list[PlaybackHostSnapshot] = []
        controller = PlaybackController(
            "maya:peer-001",
            "timeline",
            _mapper(),
            lambda _channel: "blender:peer-001",
            lambda _playback: None,
            applied.append,
        )

        self.assertTrue(self.transport.handle_frame(_frame(), controller))
        self.assertEqual(len(applied), 1)
        self.assertEqual(applied[0].change_id, "change-001")
        self.assertEqual(applied[0].position, 12.0)

    def test_self_origin_is_passed_through_to_controller(self) -> None:
        """self-originをTransportで先に捨てず、Controllerのloopback規則へ渡す。"""

        self.transport.subscribe()
        controller = _controller(peer_id="blender:peer-001", authority="blender:peer-001")
        self.assertFalse(self.transport.handle_frame(_frame(sender="blender:peer-001"), controller))

    def test_matching_frame_rejects_schema_raw_body_and_body_shape(self) -> None:
        """matching publishのschema、raw body、body objectをfail closedで検証する。"""

        self.transport.subscribe()
        controller = _controller()
        cases = (
            ("wrong schema", _frame(schema="ywta.other.playback.v1")),
            ("raw body", _frame(raw_body=b"binary")),
            ("list body", _frame(body=[])),
            ("missing field", _frame(body={"state": "paused"})),
        )
        for name, frame in cases:
            with self.subTest(name=name):
                with self.assertRaises(PlaybackTransportError):
                    self.transport.handle_frame(frame, controller)

    def test_handle_frame_requires_exact_frame_and_controller_types(self) -> None:
        """FrameとControllerの派生型を厳密に拒否する。"""

        self.transport.subscribe()

        class DerivedFrame(Frame):
            """厳密Frame検証用の派生型。"""

        class DerivedController(PlaybackController):
            """厳密Controller検証用の派生型。"""

        with self.assertRaises(PlaybackTransportError):
            self.transport.handle_frame(DerivedFrame(_frame().envelope), _controller())
        with self.assertRaises(PlaybackTransportError):
            self.transport.handle_frame(
                _frame(), DerivedController("maya", "timeline", _mapper(), lambda _: "blender", lambda _: None, lambda _: None)
            )

    def test_close_unsubscribes_once_and_does_not_close_shared_client(self) -> None:
        """closeが購読解除後にclosedとなり、借用Clientを閉じない。"""

        self.transport.subscribe()
        self.assertTrue(self.transport.close())
        self.assertFalse(self.transport.close())
        self.assertTrue(self.transport.closed)
        self.assertFalse(self.transport.active)
        self.assertEqual(self.client.unsubscribe_calls, [("shot-010", "sync/timeline/playback")])
        self.assertEqual(self.client.close_calls, 0)

    def test_close_before_subscribe_is_safe(self) -> None:
        """未購読のcloseはunsubscribeせず完了する。"""

        self.assertTrue(self.transport.close())
        self.assertEqual(self.client.unsubscribe_calls, [])
        self.assertTrue(self.transport.closed)

    def test_unsubscribe_failure_keeps_retryable_state(self) -> None:
        """unsubscribe失敗時はactive・未closedを保持して再試行できる。"""

        self.transport.subscribe()
        self.client.fail_unsubscribe = True
        with self.assertRaisesRegex(PlaybackTransportError, "unsubscribe failed"):
            self.transport.close()
        self.assertTrue(self.transport.active)
        self.assertFalse(self.transport.closed)
        self.client.fail_unsubscribe = False
        self.assertTrue(self.transport.close())

    def test_room_topic_lease_is_exclusive_until_successful_close(self) -> None:
        """同じClientの同一Room/Topicを二重所有させない。"""

        self.transport.subscribe()
        with self.assertRaisesRegex(PlaybackTransportError, "already owned"):
            PlaybackTopicTransport(self.client, "shot-010", "sync/timeline/playback")

        other = PlaybackTopicTransport(self.client, "shot-010", "sync/other/playback")
        other.close()

        self.client.fail_unsubscribe = True
        with self.assertRaises(PlaybackTransportError):
            self.transport.close()
        with self.assertRaisesRegex(PlaybackTransportError, "already owned"):
            PlaybackTopicTransport(self.client, "shot-010", "sync/timeline/playback")

        self.client.fail_unsubscribe = False
        self.transport.close()
        replacement = PlaybackTopicTransport(self.client, "shot-010", "sync/timeline/playback")
        replacement.close()

    def test_topic_lease_uses_client_identity_and_reclaims_dead_owner(self) -> None:
        """値が等しい別Clientを分離し、GC済みownerのleaseを再利用する。"""

        class EqualClient(_FakeClient):
            """全instanceが値として等しいClient代替。"""

            def __eq__(self, other: object) -> bool:
                return isinstance(other, EqualClient)

            def __hash__(self) -> int:
                return 1

        first_client = EqualClient()
        second_client = EqualClient()
        first = PlaybackTopicTransport(first_client, "room", "topic")
        second = PlaybackTopicTransport(second_client, "room", "topic")
        first.close()
        second.close()

        abandoned = PlaybackTopicTransport(self.client, "room", "gc-topic")
        abandoned_ref = weakref.ref(abandoned)
        del abandoned
        gc.collect()
        self.assertIsNone(abandoned_ref())
        replacement = PlaybackTopicTransport(self.client, "room", "gc-topic")
        replacement.close()

    def test_closed_transport_rejects_operations(self) -> None:
        """closed後のsubscribe、publish、handleは明示的に拒否する。"""

        self.transport.close()
        with self.assertRaises(PlaybackTransportError):
            self.transport.subscribe()
        with self.assertRaises(PlaybackTransportError):
            self.transport.publish(_playback())
        with self.assertRaises(PlaybackTransportError):
            self.transport.handle_frame(_frame(), _controller())

    def test_owner_thread_is_required_for_all_operations(self) -> None:
        """生成元thread以外の操作を専用のThreadErrorで拒否する。"""

        self.transport.subscribe()
        errors: list[Exception] = []

        def call_from_worker() -> None:
            for operation in (
                lambda: self.transport.publish(_playback()),
                lambda: self.transport.handle_frame(_frame(), _controller()),
                self.transport.close,
            ):
                try:
                    operation()
                except Exception as exc:
                    errors.append(exc)

        worker = threading.Thread(target=call_from_worker)
        worker.start()
        worker.join()
        self.assertEqual([type(error) for error in errors], [PlaybackTransportThreadError] * 3)
        self.assertFalse(self.transport.closed)

    def test_constructor_requires_client_methods_and_identifiers(self) -> None:
        """Client interfaceとRoom/Topic identifierを検証する。"""

        for value in (None, "", " ", 1):
            with self.subTest(value=value):
                with self.assertRaises(PlaybackTransportError):
                    PlaybackTopicTransport(self.client, value, "topic")  # type: ignore[arg-type]
                with self.assertRaises(PlaybackTransportError):
                    PlaybackTopicTransport(self.client, "room", value)  # type: ignore[arg-type]
        with self.assertRaises(PlaybackTransportError):
            PlaybackTopicTransport(object(), "room", "topic")  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
