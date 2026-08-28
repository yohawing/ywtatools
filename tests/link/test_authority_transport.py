"""Authority handoff transportのrouting、順序、状態境界を検証する。"""

from __future__ import annotations

import threading
import unittest

from ywta_link import (
    AUTHORITY_ACCEPTED_SCHEMA,
    AUTHORITY_REJECTED_SCHEMA,
    AUTHORITY_REQUEST_SCHEMA,
    AUTHORITY_SNAPSHOT_REQUEST_SCHEMA,
    AUTHORITY_SNAPSHOT_SCHEMA,
    AuthorityHandoffAccepted,
    AuthorityHandoffRequest,
    AuthorityHandoffTracker,
    AuthorityHandoffTransport,
    AuthoritySnapshot,
    AuthoritySnapshotRequest,
    AuthorityTransportError,
    AuthorityTransportThreadError,
    AuthorityValidationError,
    Envelope,
    Frame,
    PlaybackTopicTransport,
)


class _FakeClient:
    """Authority transportが借用するClientの最小代替。"""

    def __init__(self, peer_id: str) -> None:
        """peer identityと送信記録を初期化する。"""

        self.peer_id = peer_id
        self.calls: list[tuple[str, object]] = []
        self.fail_request = False
        self.fail_response = False
        self.fail_publish = False

    def subscribe(self, room: str, topic: str) -> str:
        """購読を記録する。"""

        self.calls.append(("subscribe", (room, topic)))
        return "subscribe-001"

    def unsubscribe(self, room: str, topic: str) -> str:
        """購読解除を記録する。"""

        self.calls.append(("unsubscribe", (room, topic)))
        return "unsubscribe-001"

    def request(self, room: str, target: str, **kwargs: object) -> str:
        """Requestを記録し、予約されたmessage IDを返す。"""

        if self.fail_request:
            raise RuntimeError("request failed")
        self.calls.append(("request", (room, target, dict(kwargs))))
        return kwargs["message_id"]  # type: ignore[return-value]

    def response(self, room: str, target: str, correlation_id: str, **kwargs: object) -> str:
        """Responseを記録する。"""

        if self.fail_response:
            raise RuntimeError("response failed")
        self.calls.append(("response", (room, target, correlation_id, dict(kwargs))))
        return f"response-{len(self.calls)}"

    def publish(self, room: str, **kwargs: object) -> str:
        """Publishを記録する。"""

        if self.fail_publish:
            raise RuntimeError("publish failed")
        self.calls.append(("publish", (room, dict(kwargs))))
        return f"publish-{len(self.calls)}"


def _request(change_id: str = "change-001") -> AuthorityHandoffRequest:
    """テスト用handoff requestを作る。"""

    return AuthorityHandoffRequest(
        session_id="session-001",
        channel_id="timeline",
        current_authority="blender:peer-001",
        next_authority="maya:peer-001",
        expected_authority_revision=0,
        change_id=change_id,
    )


def _frame(
    *,
    message_id: str,
    message_type: str,
    sender: str,
    target: str | None = None,
    schema: str,
    body: object,
    topic: str | None = None,
    correlation_id: str | None = None,
    raw_body: bytes = b"",
) -> Frame:
    """テスト用Envelope/Frameを作る。"""

    return Frame(
        Envelope(
            protocol_version=1,
            message_id=message_id,
            type=message_type,
            sender=sender,
            room="room-001",
            target=target,
            topic=topic,
            correlation_id=correlation_id,
            schema=schema,
            body=body,
        ),
        raw_body,
    )


class AuthorityHandoffTransportTest(unittest.TestCase):
    """Authority transportのlifecycleとwire境界を検証する。"""

    def setUp(self) -> None:
        """Requesterと現在Authorityのtransportを用意する。"""

        self.authority_client = _FakeClient("blender:peer-001")
        self.requester_client = _FakeClient("maya:peer-001")
        self.authority_tracker = AuthorityHandoffTracker({"timeline": "blender:peer-001"}, session_id="session-001")
        self.requester_tracker = AuthorityHandoffTracker({"timeline": "blender:peer-001"}, session_id="session-001")
        self.authority = AuthorityHandoffTransport(self.authority_client, "room-001", self.authority_tracker)
        self.requester = AuthorityHandoffTransport(self.requester_client, "room-001", self.requester_tracker)
        self.authority.subscribe()
        self.requester.subscribe()

    def tearDown(self) -> None:
        """購読を解除する。"""

        if not self.authority.closed:
            self.authority.close()
        if not self.requester.closed:
            self.requester.close()

    def test_subscribe_uses_session_control_topic_and_is_idempotent(self) -> None:
        """control topicを購読し、二度目のsubscribeを送信しない。"""

        self.assertEqual(self.authority.topic, "sync/session-001/control")
        self.assertFalse(self.authority.subscribe())
        self.assertEqual(
            self.authority_client.calls,
            [("subscribe", ("room-001", "sync/session-001/control"))],
        )

    def test_shared_client_can_also_own_playback_topic_transport(self) -> None:
        """Authority controlとPlayback topicは同じClient上で共存する。"""

        playback = PlaybackTopicTransport(self.authority_client, "room-001", "sync/timeline/playback")
        self.addCleanup(playback.close)
        self.assertTrue(playback.subscribe())
        self.assertTrue(self.authority.active)

    def test_request_registers_pending_before_client_send(self) -> None:
        """Request送信時はClient呼出しより先にlocal pendingを登録する。"""

        request = _request()
        observed: list[bool] = []

        def request_call(room: str, target: str, **kwargs: object) -> str:
            observed.append(self.requester_tracker.pending_for("timeline") is not None)
            self.requester_client.calls.append(("request", (room, target, dict(kwargs))))
            return kwargs["message_id"]  # type: ignore[return-value]

        self.requester_client.request = request_call  # type: ignore[method-assign]
        message_id = self.requester.request_handoff(request)

        self.assertTrue(observed)
        self.assertTrue(observed[0])
        self.assertEqual(self.requester_tracker.pending_for("timeline").request, request)  # type: ignore[union-attr]
        request_call_data = self.requester_client.calls[-1][1]  # type: ignore[index]
        self.assertEqual(request_call_data[2]["message_id"], message_id)  # type: ignore[index]
        self.assertEqual(request_call_data[2]["schema"], AUTHORITY_REQUEST_SCHEMA)  # type: ignore[index]

    def test_received_request_only_registers_pending_until_explicit_decision(self) -> None:
        """現在AuthorityはRequest受信だけで勝手にacceptしない。"""

        request = _request()
        handled = self.authority.handle_frame(
            _frame(
                message_id="request-001",
                message_type="request",
                sender=request.next_authority,
                target=request.current_authority,
                schema=AUTHORITY_REQUEST_SCHEMA,
                body=request.to_dict(),
            )
        )

        self.assertTrue(handled)
        self.assertEqual(self.authority_tracker.pending_for("timeline").request, request)  # type: ignore[union-attr]
        self.assertEqual([name for name, _ in self.authority_client.calls], ["subscribe"])

    def test_snapshot_request_returns_exact_current_state(self) -> None:
        """Snapshot Requestへ現在Authorityとrevisionをtarget responseで返す。"""

        request = AuthoritySnapshotRequest(session_id="session-001", channel_id="timeline")
        handled = self.authority.handle_frame(
            _frame(
                message_id="snapshot-request-001",
                message_type="request",
                sender="maya:peer-001",
                target="blender:peer-001",
                schema=AUTHORITY_SNAPSHOT_REQUEST_SCHEMA,
                body=request.to_dict(),
            )
        )

        self.assertTrue(handled)
        response = self.authority_client.calls[-1]
        self.assertEqual(response[0], "response")
        self.assertEqual(
            response[1],
            (
                "room-001",
                "maya:peer-001",
                "snapshot-request-001",
                {
                    "schema": AUTHORITY_SNAPSHOT_SCHEMA,
                    "body": {
                        "session_id": "session-001",
                        "channel_id": "timeline",
                        "authority": "blender:peer-001",
                        "authority_revision": 0,
                    },
                },
            ),
        )

    def test_snapshot_request_returns_latest_handoff_revision(self) -> None:
        """Handoff後の照会は更新済みAuthority stateを返す。"""

        handoff = _request()
        self.authority.handle_frame(
            _frame(
                message_id="handoff-request-001",
                message_type="request",
                sender=handoff.next_authority,
                target=handoff.current_authority,
                schema=AUTHORITY_REQUEST_SCHEMA,
                body=handoff.to_dict(),
            )
        )
        self.authority.accept_handoff(handoff)

        self.authority.handle_frame(
            _frame(
                message_id="snapshot-request-001",
                message_type="request",
                sender="maya:peer-002",
                target="blender:peer-001",
                schema=AUTHORITY_SNAPSHOT_REQUEST_SCHEMA,
                body={"session_id": "session-001", "channel_id": "timeline"},
            )
        )

        body = self.authority_client.calls[-1][1][3]["body"]  # type: ignore[index]
        self.assertEqual(body["authority"], "maya:peer-001")
        self.assertEqual(body["authority_revision"], 1)

    def test_malformed_snapshot_requests_fail_closed(self) -> None:
        """Snapshot Requestのroutingとbody不整合を拒否する。"""

        base = {
            "message_id": "snapshot-request-001",
            "message_type": "request",
            "sender": "maya:peer-001",
            "target": "blender:peer-001",
            "schema": AUTHORITY_SNAPSHOT_REQUEST_SCHEMA,
            "body": {"session_id": "session-001", "channel_id": "timeline"},
        }
        overrides = (
            {"target": "other:peer-001"},
            {"sender": "blender:peer-001"},
            {"correlation_id": "unexpected"},
            {"body": {"session_id": "other-session", "channel_id": "timeline"}},
            {"body": {"session_id": "session-001", "channel_id": "missing"}},
            {"body": {"session_id": "session-001", "channel_id": "timeline", "extra": True}},
            {"raw_body": b"binary"},
            {"topic": "sync/session-001/control"},
        )
        for index, override in enumerate(overrides):
            values = dict(base)
            values.update(override)
            values["message_id"] = f"snapshot-request-{index + 1:03d}"
            with self.subTest(override=override):
                with self.assertRaises(AuthorityTransportError):
                    self.authority.handle_frame(_frame(**values))  # type: ignore[arg-type]

    def test_snapshot_response_send_failure_latches_failed(self) -> None:
        """Snapshot response送信失敗をterminal Failedへ固定する。"""

        self.authority_client.fail_response = True
        with self.assertRaisesRegex(AuthorityTransportError, "response failed"):
            self.authority.handle_frame(
                _frame(
                    message_id="snapshot-request-001",
                    message_type="request",
                    sender="maya:peer-001",
                    target="blender:peer-001",
                    schema=AUTHORITY_SNAPSHOT_REQUEST_SCHEMA,
                    body={"session_id": "session-001", "channel_id": "timeline"},
                )
            )

        self.assertTrue(self.authority.failed)

    def test_snapshot_response_non_string_id_latches_failed(self) -> None:
        """Client responseの不正なmessage IDもterminal Failedにする。"""

        self.authority_client.response = lambda *args, **kwargs: None  # type: ignore[method-assign]
        with self.assertRaisesRegex(AuthorityTransportError, "non-empty string"):
            self.authority.handle_frame(
                _frame(
                    message_id="snapshot-request-001",
                    message_type="request",
                    sender="maya:peer-001",
                    target="blender:peer-001",
                    schema=AUTHORITY_SNAPSHOT_REQUEST_SCHEMA,
                    body={"session_id": "session-001", "channel_id": "timeline"},
                )
            )

        self.assertTrue(self.authority.failed)

    def test_incoming_snapshot_response_is_consumed_without_state_mutation(self) -> None:
        """Runtimeへ届いたsnapshot responseは検証後にTrackerへ適用しない。"""

        before = self.requester_tracker.state_for("timeline")
        snapshot = AuthoritySnapshot(
            session_id="session-001",
            channel_id="timeline",
            authority="maya:peer-999",
            authority_revision=42,
        )
        handled = self.requester.handle_frame(
            _frame(
                message_id="snapshot-response-001",
                message_type="response",
                sender="blender:peer-001",
                target="maya:peer-001",
                correlation_id="bootstrap-request-001",
                schema=AUTHORITY_SNAPSHOT_SCHEMA,
                body=snapshot.to_dict(),
            )
        )

        self.assertTrue(handled)
        self.assertEqual(self.requester_tracker.state_for("timeline"), before)

    def test_malformed_snapshot_responses_fail_closed(self) -> None:
        """未所有Snapshot Responseでもroutingとbodyを厳密に検証する。"""

        base = {
            "message_id": "snapshot-response-001",
            "message_type": "response",
            "sender": "blender:peer-001",
            "target": "maya:peer-001",
            "correlation_id": "bootstrap-request-001",
            "schema": AUTHORITY_SNAPSHOT_SCHEMA,
            "body": {
                "session_id": "session-001",
                "channel_id": "timeline",
                "authority": "blender:peer-001",
                "authority_revision": 0,
            },
        }
        overrides = (
            {"target": "other:peer-001"},
            {"sender": "maya:peer-001"},
            {"body": {"session_id": "session-001", "channel_id": "timeline"}},
            {
                "body": {
                    "session_id": "other-session",
                    "channel_id": "timeline",
                    "authority": "blender:peer-001",
                    "authority_revision": 0,
                }
            },
            {
                "body": {
                    "session_id": "session-001",
                    "channel_id": "missing",
                    "authority": "blender:peer-001",
                    "authority_revision": 0,
                }
            },
            {"raw_body": b"binary"},
            {"topic": "sync/session-001/control"},
        )
        for index, override in enumerate(overrides):
            values = dict(base)
            values.update(override)
            values["message_id"] = f"snapshot-response-{index + 1:03d}"
            with self.subTest(override=override):
                with self.assertRaises(AuthorityTransportError):
                    self.requester.handle_frame(_frame(**values))  # type: ignore[arg-type]

    def test_snapshot_frame_for_other_room_is_unrelated(self) -> None:
        """別RoomのSnapshot FrameはこのTransportの処理対象にしない。"""

        frame = _frame(
            message_id="snapshot-request-001",
            message_type="request",
            sender="maya:peer-001",
            target="blender:peer-001",
            schema=AUTHORITY_SNAPSHOT_REQUEST_SCHEMA,
            body={"session_id": "session-001", "channel_id": "timeline"},
        )
        foreign = Frame(
            Envelope(
                protocol_version=1,
                message_id=frame.envelope.message_id,
                type=frame.envelope.type,
                sender=frame.envelope.sender,
                room="room-other",
                target=frame.envelope.target,
                schema=frame.envelope.schema,
                body=frame.envelope.body,
            ),
            frame.body,
        )

        self.assertFalse(self.authority.handle_frame(foreign))

    def test_snapshot_wire_types_reject_unknown_fields_and_invalid_revision(self) -> None:
        """公開snapshot型はField過不足とrevision型を厳密に拒否する。"""

        with self.assertRaises(AuthorityValidationError):
            AuthoritySnapshotRequest.from_dict({"session_id": "session-001", "channel_id": "timeline", "extra": True})
        with self.assertRaises(AuthorityValidationError):
            AuthoritySnapshot.from_dict(
                {
                    "session_id": "session-001",
                    "channel_id": "timeline",
                    "authority": "blender:peer-001",
                    "authority_revision": True,
                }
            )

    def test_accept_sends_response_before_accepted_fanout_and_updates_authority(self) -> None:
        """acceptはTracker更新後にtarget response、Accepted publishの順で送信する。"""

        request = _request()
        self.authority.handle_frame(
            _frame(
                message_id="request-001",
                message_type="request",
                sender=request.next_authority,
                target=request.current_authority,
                schema=AUTHORITY_REQUEST_SCHEMA,
                body=request.to_dict(),
            )
        )
        response_id, publish_id = self.authority.accept_handoff(request)

        self.assertTrue(response_id)
        self.assertTrue(publish_id)
        self.assertEqual(self.authority_tracker.state_for("timeline").authority, request.next_authority)
        self.assertEqual(
            [name for name, _ in self.authority_client.calls],
            ["subscribe", "response", "publish"],
        )
        response = self.authority_client.calls[1][1]  # type: ignore[index]
        publish = self.authority_client.calls[2][1]  # type: ignore[index]
        self.assertEqual(response[1], request.next_authority)  # type: ignore[index]
        self.assertEqual(response[2], "request-001")  # type: ignore[index]
        self.assertEqual(response[3]["schema"], AUTHORITY_ACCEPTED_SCHEMA)  # type: ignore[index]
        self.assertEqual(publish[1]["topic"], "sync/session-001/control")  # type: ignore[index]
        self.assertEqual(publish[1]["correlation_id"], "request-001")  # type: ignore[index]

    def test_accept_publish_failure_latches_failed_but_close_succeeds(self) -> None:
        """Accepted publish失敗後はfailedを保持し、closeだけを許可する。"""

        request = _request()
        self.authority.handle_frame(
            _frame(
                message_id="request-001",
                message_type="request",
                sender=request.next_authority,
                target=request.current_authority,
                schema=AUTHORITY_REQUEST_SCHEMA,
                body=request.to_dict(),
            )
        )
        self.authority_client.fail_publish = True

        with self.assertRaisesRegex(AuthorityTransportError, "publish failed"):
            self.authority.accept_handoff(request)

        self.assertTrue(self.authority.failed)
        self.assertEqual(self.authority_tracker.state_for("timeline").authority, request.next_authority)
        for operation in (
            lambda: self.authority.subscribe(),
            lambda: self.authority.request_handoff(request),
            lambda: self.authority.handle_frame(
                _frame(
                    message_id="request-002",
                    message_type="request",
                    sender=request.next_authority,
                    target=request.current_authority,
                    schema=AUTHORITY_REQUEST_SCHEMA,
                    body=request.to_dict(),
                )
            ),
            lambda: self.authority.accept_handoff(request),
            lambda: self.authority.reject_handoff(request, "busy"),
        ):
            with self.subTest(operation=operation):
                with self.assertRaisesRegex(AuthorityTransportError, "has failed"):
                    operation()

        self.authority_client.fail_publish = False
        self.assertTrue(self.authority.close())
        self.assertTrue(self.authority.closed)

    def test_request_send_failure_latches_failed_and_close_remains_allowed(self) -> None:
        """pending登録後のRequest送信失敗をfailedへ固定する。"""

        self.requester_client.fail_request = True
        with self.assertRaisesRegex(AuthorityTransportError, "request failed"):
            self.requester.request_handoff(_request())

        self.assertTrue(self.requester.failed)
        self.assertIsNotNone(self.requester_tracker.pending_for("timeline"))
        self.requester_client.fail_request = False
        self.assertTrue(self.requester.close())

    def test_accepted_response_does_not_update_requester_until_publish(self) -> None:
        """Requesterはtarget Accepted responseではstateを変更しない。"""

        request = _request()
        request_message_id = self.requester.request_handoff(request)
        accepted = AuthorityHandoffAccepted(
            session_id=request.session_id,
            channel_id=request.channel_id,
            current_authority=request.current_authority,
            next_authority=request.next_authority,
            expected_authority_revision=0,
            new_authority_revision=1,
            change_id=request.change_id,
        )
        response = _frame(
            message_id="response-001",
            message_type="response",
            sender=request.current_authority,
            target=request.next_authority,
            schema=AUTHORITY_ACCEPTED_SCHEMA,
            body=accepted.to_dict(),
            correlation_id=request_message_id,
        )
        self.assertTrue(self.requester.handle_frame(response))
        self.assertEqual(self.requester_tracker.state_for("timeline").authority, request.current_authority)
        self.assertIsNotNone(self.requester_tracker.pending_for("timeline"))

        publish = _frame(
            message_id="publish-001",
            message_type="publish",
            sender=request.current_authority,
            schema=AUTHORITY_ACCEPTED_SCHEMA,
            body=accepted.to_dict(),
            topic="sync/session-001/control",
            correlation_id=request_message_id,
        )
        self.assertTrue(self.requester.handle_frame(publish))
        self.assertEqual(self.requester_tracker.state_for("timeline").authority, request.next_authority)
        self.assertIsNone(self.requester_tracker.pending_for("timeline"))

    def test_reject_sends_only_target_response_and_keeps_state(self) -> None:
        """rejectはtarget responseだけを送り、Authority stateを変更しない。"""

        request = _request()
        self.authority.handle_frame(
            _frame(
                message_id="request-001",
                message_type="request",
                sender=request.next_authority,
                target=request.current_authority,
                schema=AUTHORITY_REQUEST_SCHEMA,
                body=request.to_dict(),
            )
        )
        self.authority.reject_handoff(request, "busy")

        self.assertEqual(self.authority_tracker.state_for("timeline").authority, request.current_authority)
        self.assertEqual([name for name, _ in self.authority_client.calls], ["subscribe", "response"])
        response = self.authority_client.calls[1][1]  # type: ignore[index]
        self.assertEqual(response[3]["schema"], AUTHORITY_REJECTED_SCHEMA)  # type: ignore[index]

    def test_malformed_control_frames_fail_closed(self) -> None:
        """control routing identityとraw bodyの不正を拒否する。"""

        request = _request()
        cases = (
            _frame(
                message_id="request-001",
                message_type="request",
                sender="other:peer-001",
                target=request.current_authority,
                schema=AUTHORITY_REQUEST_SCHEMA,
                body=request.to_dict(),
            ),
            _frame(
                message_id="request-002",
                message_type="request",
                sender=request.next_authority,
                target=request.current_authority,
                schema=AUTHORITY_REQUEST_SCHEMA,
                body=request.to_dict(),
                raw_body=b"binary",
            ),
            _frame(
                message_id="publish-001",
                message_type="publish",
                sender=request.current_authority,
                schema=AUTHORITY_ACCEPTED_SCHEMA,
                body={"bad": True},
                topic="sync/session-001/control",
                correlation_id="request-001",
            ),
            _frame(
                message_id="publish-002",
                message_type="publish",
                sender=request.current_authority,
                schema=AUTHORITY_ACCEPTED_SCHEMA,
                body=AuthorityHandoffAccepted(
                    session_id=request.session_id,
                    channel_id=request.channel_id,
                    current_authority=request.current_authority,
                    next_authority=request.next_authority,
                    expected_authority_revision=0,
                    new_authority_revision=1,
                    change_id=request.change_id,
                ).to_dict(),
                topic="sync/session-001/control",
                correlation_id="request-001",
                raw_body=b"binary",
            ),
        )
        for frame in cases:
            with self.subTest(frame=frame.envelope.message_id):
                with self.assertRaises(AuthorityTransportError):
                    self.authority.handle_frame(frame)

    def test_close_is_idempotent_and_owner_thread_limited(self) -> None:
        """closeは冪等で、owner以外からの操作を拒否する。"""

        errors: list[BaseException] = []

        def close_from_worker() -> None:
            try:
                self.authority.close()
            except BaseException as exc:
                errors.append(exc)

        worker = threading.Thread(target=close_from_worker)
        worker.start()
        worker.join()
        self.assertIsInstance(errors[0], AuthorityTransportThreadError)
        self.assertTrue(self.authority.close())
        self.assertFalse(self.authority.close())


if __name__ == "__main__":
    unittest.main()
