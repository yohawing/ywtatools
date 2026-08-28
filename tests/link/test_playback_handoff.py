"""Playback handoff CoordinatorのMain Thread境界と順序を検証する。"""

from __future__ import annotations

import threading
import time
import unittest

from ywta_link import (
    AUTHORITY_ACCEPTED_SCHEMA,
    AUTHORITY_REJECTED_SCHEMA,
    AUTHORITY_REQUEST_SCHEMA,
    AuthorityHandoffAccepted,
    AuthorityHandoffRequest,
    AuthorityHandoffTracker,
    AuthorityHandoffTransport,
    Envelope,
    Frame,
    Playback,
    PlaybackController,
    PlaybackHandoffCoordinator,
    PlaybackHandoffError,
    PlaybackHandoffThreadError,
    PlaybackHostEvent,
    PlaybackHostEventKind,
    PlaybackHostRange,
    PlaybackHostSnapshot,
    PlaybackTimeMapper,
    RationalRate,
    Time,
)


class _Client:
    """Authority transportが借用する送信記録用Client。"""

    def __init__(self, peer_id: str) -> None:
        """peer identityと呼び出し記録を初期化する。"""

        self.peer_id = peer_id
        self.calls: list[tuple[str, object]] = []
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
        """Requestを記録し、予約済みmessage IDを返す。"""

        self.calls.append(("request", (room, target, dict(kwargs))))
        return kwargs["message_id"]  # type: ignore[return-value]

    def response(self, room: str, target: str, correlation_id: str, **kwargs: object) -> str:
        """Responseを記録する。"""

        self.calls.append(("response", (room, target, correlation_id, dict(kwargs))))
        return f"response-{len(self.calls)}"

    def publish(self, room: str, **kwargs: object) -> str:
        """Accepted fan-outを記録する。"""

        if self.fail_publish:
            raise RuntimeError("publish failed")
        self.calls.append(("publish", (room, dict(kwargs))))
        return f"publish-{len(self.calls)}"


class _Clock:
    """テストから進められるmonotonic clock。"""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        """現在値を返す。"""

        return self.now


def _snapshot(change_id: str) -> PlaybackHostSnapshot:
    """テスト用のPlayback snapshotを返す。"""

    return PlaybackHostSnapshot(
        state="paused",
        position=12,
        playback_range=PlaybackHostRange(0, 24),
        speed=1.0,
        direction="forward",
        loop_mode="once",
        time_unit="frames",
        change_id=change_id,
    )


def _event(change_id: str) -> PlaybackHostEvent:
    """テスト用のHost eventを返す。"""

    return PlaybackHostEvent(PlaybackHostEventKind.PAUSED_SEEK, _snapshot(change_id))


def _frame(
    *,
    message_id: str,
    message_type: str,
    sender: str,
    target: str | None,
    schema: str,
    body: object,
    topic: str | None = None,
    correlation_id: str | None = None,
) -> Frame:
    """テスト用のAuthority Frameを返す。"""

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
        )
    )


class PlaybackHandoffCoordinatorTest(unittest.TestCase):
    """Playback eventとAuthority stateの結合を検証する。"""

    def test_exposes_borrowed_component_properties(self) -> None:
        """Runtimeが借用componentのidentityを公開契約だけで照合できる。"""

        coordinator, tracker, client, _published, _applied = self._make()
        self.assertIs(coordinator.tracker, tracker)
        self.assertIs(coordinator.authority_transport.tracker, tracker)
        self.assertIs(coordinator.authority_transport.client, client)
        self.assertIs(type(coordinator.controller), PlaybackController)
        with self.assertRaises(AttributeError):
            coordinator.tracker = tracker  # type: ignore[misc]

    def _make(
        self,
        authority: str = "peer-remote",
        clock: _Clock | None = None,
        fail_publish: bool = False,
        rollback_apply: object | None = None,
        observe_remote: bool = False,
    ) -> tuple[PlaybackHandoffCoordinator, AuthorityHandoffTracker, _Client, list[object], list[PlaybackHostSnapshot]]:
        """実Transport/Controllerを使ったCoordinatorを構成する。"""

        client = _Client("peer-local")
        tracker = AuthorityHandoffTracker({"timeline": authority}, session_id="session-001")
        authority_transport = AuthorityHandoffTransport(client, "room-001", tracker)
        authority_transport.subscribe()
        published: list[object] = []
        applied: list[PlaybackHostSnapshot] = []

        def publish(playback: object) -> str:
            """Playback publishを記録し、必要なら失敗させる。"""

            if fail_publish:
                raise RuntimeError("publish failed")
            published.append(playback)
            return "playback-001"

        rollback = (lambda snapshot: applied.append(snapshot)) if rollback_apply is None else rollback_apply
        mapper = PlaybackTimeMapper(
            ticks_per_host_unit=1,
            host_unit_rate=RationalRate(24, 1),
            time_unit="frames",
        )
        controller = PlaybackController(
            "peer-local",
            "timeline",
            mapper,
            lambda channel: tracker.state_for(channel).authority,
            publish,
            lambda snapshot: applied.append(snapshot),
        )
        coordinator = PlaybackHandoffCoordinator(
            "peer-local",
            "timeline",
            tracker,
            authority_transport,
            controller,
            _snapshot("baseline-001"),
            rollback,  # type: ignore[arg-type]
            1.0,
            time.monotonic if clock is None else clock,
        )
        if observe_remote:

            def observe_remote_apply(snapshot: PlaybackHostSnapshot) -> None:
                """remote apply成功後にCoordinatorのbaselineを更新する。"""

                applied.append(snapshot)
                coordinator.observe_authoritative_snapshot(snapshot)

            controller._host_apply = observe_remote_apply  # noqa: SLF001 - relay test seam
        self.addCleanup(coordinator.close)
        return coordinator, tracker, client, published, applied

    @staticmethod
    def _remote_playback(change_id: str) -> Playback:
        """テスト用のremote Playback payloadを作る。"""

        rate = RationalRate(24, 1)
        return Playback(
            state="paused",
            position=Time(18, None, None, rate),
            playback_range=Time(None, 0, 24, rate),
            speed=1.0,
            direction="forward",
            loop_mode="once",
            change_id=change_id,
        )

    def test_local_authority_publishes_and_updates_baseline(self) -> None:
        """local Authority eventは直接publishし、成功後だけbaselineを進める。"""

        coordinator, tracker, _client, published, applied = self._make("peer-local")
        self.assertTrue(coordinator.handle_host_event(_event("change-local")))
        self.assertEqual([item.change_id for item in published], ["change-local"])
        request = AuthorityHandoffRequest(
            session_id="session-001",
            channel_id="timeline",
            current_authority="peer-local",
            next_authority="peer-remote",
            expected_authority_revision=0,
            change_id="remote-change",
        )
        coordinator.handle_authority_frame(
            _frame(
                message_id="inbound-request",
                message_type="request",
                sender="peer-remote",
                target="peer-local",
                schema=AUTHORITY_REQUEST_SCHEMA,
                body=request.to_dict(),
            )
        )
        coordinator.handle_host_event(_event("change-pending"))
        pending = tracker.pending_for("timeline")
        self.assertIsNotNone(pending)
        rejected = _frame(
            message_id="rejected-response",
            message_type="response",
            sender="peer-remote",
            target="peer-local",
            schema=AUTHORITY_REJECTED_SCHEMA,
            body={**pending.request.to_dict(), "reason": "busy"},  # type: ignore[union-attr]
            correlation_id=pending.request_message_id,  # type: ignore[union-attr]
        )
        coordinator.handle_authority_frame(rejected)
        self.assertEqual([snapshot.change_id for snapshot in applied], ["change-local"])
        self.assertFalse(coordinator.status.pending)

    def test_non_authority_requests_once_and_coalesces_latest_event(self) -> None:
        """非AuthorityはRequestを一度だけ送り、最新eventを保持する。"""

        coordinator, tracker, client, published, _applied = self._make()
        self.assertFalse(coordinator.handle_host_event(_event("change-first")))
        self.assertFalse(coordinator.handle_host_event(_event("change-latest")))
        self.assertEqual([name for name, _ in client.calls].count("request"), 1)
        self.assertEqual(tracker.pending_for("timeline").request.change_id, "change-first")  # type: ignore[union-attr]
        self.assertEqual(published, [])

    def test_accepted_response_does_not_publish(self) -> None:
        """Accepted target responseはcontrol publishまでpublishしない。"""

        coordinator, tracker, client, published, _applied = self._make()
        coordinator.handle_host_event(_event("change-latest"))
        request = tracker.pending_for("timeline").request  # type: ignore[union-attr]
        request_message_id = tracker.pending_for("timeline").request_message_id  # type: ignore[union-attr]
        accepted = AuthorityHandoffAccepted(
            session_id=request.session_id,
            channel_id=request.channel_id,
            current_authority=request.current_authority,
            next_authority=request.next_authority,
            expected_authority_revision=0,
            new_authority_revision=1,
            change_id=request.change_id,
        )
        frame = _frame(
            message_id="accepted-response",
            message_type="response",
            sender="peer-remote",
            target="peer-local",
            schema=AUTHORITY_ACCEPTED_SCHEMA,
            body=accepted.to_dict(),
            correlation_id=request_message_id,
        )
        self.assertTrue(coordinator.handle_authority_frame(frame))
        self.assertEqual(published, [])
        self.assertTrue(coordinator.status.pending)
        self.assertEqual([name for name, _ in client.calls].count("publish"), 0)

    def test_accepted_publish_publishes_latest_event_once(self) -> None:
        """Accepted control publish後に最新保留eventを一度だけpublishする。"""

        coordinator, tracker, _client, published, _applied = self._make()
        coordinator.handle_host_event(_event("change-first"))
        coordinator.handle_host_event(_event("change-latest"))
        pending = tracker.pending_for("timeline")
        self.assertIsNotNone(pending)
        request = pending.request  # type: ignore[union-attr]
        accepted = AuthorityHandoffAccepted(
            session_id=request.session_id,
            channel_id=request.channel_id,
            current_authority=request.current_authority,
            next_authority=request.next_authority,
            expected_authority_revision=0,
            new_authority_revision=1,
            change_id=request.change_id,
        )
        frame = _frame(
            message_id="accepted-publish",
            message_type="publish",
            sender="peer-remote",
            target=None,
            schema=AUTHORITY_ACCEPTED_SCHEMA,
            body=accepted.to_dict(),
            topic="sync/session-001/control",
            correlation_id=pending.request_message_id,  # type: ignore[union-attr]
        )
        self.assertTrue(coordinator.handle_authority_frame(frame))
        self.assertEqual([item.change_id for item in published], ["change-latest"])
        self.assertFalse(coordinator.status.pending)

    def test_remote_apply_during_pending_is_overwritten_before_accepted_publish(self) -> None:
        """pending中の旧Authority apply後もAccepted時は保留snapshotを最終適用する。"""

        coordinator, tracker, _client, published, applied = self._make(observe_remote=True)
        coordinator.handle_host_event(_event("change-latest"))
        pending = tracker.pending_for("timeline")
        self.assertIsNotNone(pending)
        coordinator.controller.apply_remote("peer-remote", self._remote_playback("remote-old"))
        self.assertEqual([snapshot.change_id for snapshot in applied], ["remote-old"])
        request = pending.request  # type: ignore[union-attr]
        accepted = AuthorityHandoffAccepted(
            session_id=request.session_id,
            channel_id=request.channel_id,
            current_authority=request.current_authority,
            next_authority=request.next_authority,
            expected_authority_revision=request.expected_authority_revision,
            new_authority_revision=request.expected_authority_revision + 1,
            change_id=request.change_id,
        )
        frame = _frame(
            message_id="accepted-after-remote",
            message_type="publish",
            sender="peer-remote",
            target=None,
            schema=AUTHORITY_ACCEPTED_SCHEMA,
            body=accepted.to_dict(),
            topic="sync/session-001/control",
            correlation_id=pending.request_message_id,  # type: ignore[union-attr]
        )
        coordinator.handle_authority_frame(frame)
        self.assertEqual([snapshot.change_id for snapshot in applied], ["remote-old", "change-latest"])
        self.assertEqual([item.change_id for item in published], ["change-latest"])

    def test_accepted_reapply_failure_does_not_publish_and_fails_closed(self) -> None:
        """Accepted直前の保留snapshot再適用失敗はpublishせずFailedにする。"""

        def fail_reapply(_snapshot: PlaybackHostSnapshot) -> None:
            """Accepted直前のHost再適用を失敗させる。"""

            raise RuntimeError("retained apply failed")

        coordinator, tracker, _client, published, _applied = self._make(rollback_apply=fail_reapply)
        coordinator.handle_host_event(_event("change-latest"))
        pending = tracker.pending_for("timeline")
        self.assertIsNotNone(pending)
        request = pending.request  # type: ignore[union-attr]
        accepted = AuthorityHandoffAccepted(
            session_id=request.session_id,
            channel_id=request.channel_id,
            current_authority=request.current_authority,
            next_authority=request.next_authority,
            expected_authority_revision=request.expected_authority_revision,
            new_authority_revision=request.expected_authority_revision + 1,
            change_id=request.change_id,
        )
        frame = _frame(
            message_id="accepted-reapply-failure",
            message_type="publish",
            sender="peer-remote",
            target=None,
            schema=AUTHORITY_ACCEPTED_SCHEMA,
            body=accepted.to_dict(),
            topic="sync/session-001/control",
            correlation_id=pending.request_message_id,  # type: ignore[union-attr]
        )
        with self.assertRaises(PlaybackHandoffError):
            coordinator.handle_authority_frame(frame)
        self.assertEqual([], published)
        self.assertTrue(coordinator.status.failed)

    def test_rejected_response_restores_baseline(self) -> None:
        """Rejected responseは保留eventを捨ててbaselineへrollbackする。"""

        coordinator, tracker, _client, _published, applied = self._make()
        coordinator.observe_authoritative_snapshot(_snapshot("confirmed"))
        coordinator.handle_host_event(_event("change-local"))
        request = tracker.pending_for("timeline").request  # type: ignore[union-attr]
        request_message_id = tracker.pending_for("timeline").request_message_id  # type: ignore[union-attr]
        frame = _frame(
            message_id="rejected-response",
            message_type="response",
            sender="peer-remote",
            target="peer-local",
            schema=AUTHORITY_REJECTED_SCHEMA,
            body={**request.to_dict(), "reason": "busy"},
            correlation_id=request_message_id,
        )
        self.assertTrue(coordinator.handle_authority_frame(frame))
        self.assertEqual([snapshot.change_id for snapshot in applied], ["confirmed"])
        self.assertFalse(coordinator.status.pending)

    def test_competing_accepted_winner_restores_and_discards(self) -> None:
        """別peer向けAcceptedでlocal pendingが解放された場合はrollbackする。"""

        coordinator, tracker, _client, published, applied = self._make()
        coordinator.handle_host_event(_event("change-local"))
        pending = tracker.pending_for("timeline")
        request = pending.request  # type: ignore[union-attr]
        accepted = AuthorityHandoffAccepted(
            session_id=request.session_id,
            channel_id=request.channel_id,
            current_authority=request.current_authority,
            next_authority="peer-other",
            expected_authority_revision=0,
            new_authority_revision=1,
            change_id="change-other",
        )
        frame = _frame(
            message_id="winner-publish",
            message_type="publish",
            sender="peer-remote",
            target=None,
            schema=AUTHORITY_ACCEPTED_SCHEMA,
            body=accepted.to_dict(),
            topic="sync/session-001/control",
            correlation_id="other-request",
        )
        self.assertTrue(coordinator.handle_authority_frame(frame))
        self.assertEqual(published, [])
        self.assertEqual([snapshot.change_id for snapshot in applied], ["baseline-001"])

    def test_inbound_request_is_immediately_accepted(self) -> None:
        """現在Authority向けRequestはTransportへ明示acceptを依頼する。"""

        coordinator, tracker, client, _published, _applied = self._make("peer-local")
        request = AuthorityHandoffRequest(
            session_id="session-001",
            channel_id="timeline",
            current_authority="peer-local",
            next_authority="peer-remote",
            expected_authority_revision=0,
            change_id="remote-change",
        )
        frame = _frame(
            message_id="inbound-request",
            message_type="request",
            sender="peer-remote",
            target="peer-local",
            schema=AUTHORITY_REQUEST_SCHEMA,
            body=request.to_dict(),
        )
        self.assertTrue(coordinator.handle_authority_frame(frame))
        self.assertEqual(tracker.state_for("timeline").authority, "peer-remote")
        self.assertEqual([name for name, _ in client.calls].count("response"), 1)
        self.assertEqual([name for name, _ in client.calls].count("publish"), 1)

    def test_inbound_accept_publish_failure_latches_terminal_error(self) -> None:
        """inbound RequestのAccepted fan-out失敗もFailedへ固定する。"""

        coordinator, _tracker, client, _published, _applied = self._make("peer-local")
        client.fail_publish = True
        request = AuthorityHandoffRequest(
            session_id="session-001",
            channel_id="timeline",
            current_authority="peer-local",
            next_authority="peer-remote",
            expected_authority_revision=0,
            change_id="remote-change",
        )
        frame = _frame(
            message_id="inbound-request-failure",
            message_type="request",
            sender="peer-remote",
            target="peer-local",
            schema=AUTHORITY_REQUEST_SCHEMA,
            body=request.to_dict(),
        )
        with self.assertRaises(PlaybackHandoffError):
            coordinator.handle_authority_frame(frame)
        self.assertTrue(coordinator.status.failed)
        self.assertIsNotNone(coordinator.status.error)

    def test_timeout_rolls_back_once_and_becomes_terminal(self) -> None:
        """期限切れは一度rollbackし、Tracker pendingを残したままFailedにする。"""

        clock = _Clock()
        coordinator, tracker, _client, _published, applied = self._make(clock=clock)
        coordinator.handle_host_event(_event("change-local"))
        clock.now = 1.0
        self.assertTrue(coordinator.poll_timeout())
        self.assertEqual([snapshot.change_id for snapshot in applied], ["baseline-001"])
        self.assertTrue(coordinator.status.failed)
        self.assertFalse(coordinator.status.pending)
        self.assertIsNotNone(tracker.pending_for("timeline"))
        with self.assertRaises(PlaybackHandoffError):
            coordinator.handle_host_event(_event("after-failed"))

    def test_controller_publish_failure_latches_terminal_error(self) -> None:
        """Controller publish失敗はCoordinatorにもlatched Failedとして伝播する。"""

        coordinator, _tracker, _client, _published, _applied = self._make("peer-local", fail_publish=True)
        with self.assertRaises(PlaybackHandoffError):
            coordinator.handle_host_event(_event("publish-failure"))
        self.assertTrue(coordinator.status.failed)
        self.assertIsNotNone(coordinator.status.error)
        with self.assertRaises(PlaybackHandoffError):
            coordinator.handle_host_event(_event("after-failure"))

    def test_rollback_failure_latches_terminal_error(self) -> None:
        """rollback callbackの失敗もCoordinatorをterminal Failedに固定する。"""

        def fail_rollback(_snapshot: PlaybackHostSnapshot) -> None:
            """rollbackを意図的に失敗させる。"""

            raise PlaybackHandoffError("rollback failed")

        coordinator, tracker, _client, _published, _applied = self._make(rollback_apply=fail_rollback)
        coordinator.handle_host_event(_event("rollback-failure"))
        pending = tracker.pending_for("timeline")
        self.assertIsNotNone(pending)
        request = pending.request  # type: ignore[union-attr]
        frame = _frame(
            message_id="rollback-rejected",
            message_type="response",
            sender="peer-remote",
            target="peer-local",
            schema=AUTHORITY_REJECTED_SCHEMA,
            body={**request.to_dict(), "reason": "busy"},
            correlation_id=pending.request_message_id,  # type: ignore[union-attr]
        )
        with self.assertRaises(PlaybackHandoffError):
            coordinator.handle_authority_frame(frame)
        self.assertTrue(coordinator.status.failed)
        self.assertIsNotNone(coordinator.status.error)

    def test_invalid_clock_latches_terminal_error(self) -> None:
        """monotonic clockがNaNを返した場合はFailedへ固定する。"""

        class _BadClock:
            """NaNを返すclock。"""

            def __call__(self) -> float:
                """不正な時刻を返す。"""

                return float("nan")

        coordinator, _tracker, _client, _published, _applied = self._make(clock=_BadClock())  # type: ignore[arg-type]
        with self.assertRaises(PlaybackHandoffError):
            coordinator.handle_host_event(_event("bad-clock"))
        self.assertTrue(coordinator.status.failed)
        self.assertIsNotNone(coordinator.status.error)

    def test_close_borrows_components_without_changing_their_lifecycle(self) -> None:
        """Coordinator.closeはborrowed Transport/Controllerを閉じない。"""

        coordinator, _tracker, _client, _published, _applied = self._make("peer-local")
        authority_transport = coordinator._authority_transport  # noqa: SLF001
        controller = coordinator._controller  # noqa: SLF001
        self.assertTrue(coordinator.close())
        self.assertTrue(authority_transport.active)
        self.assertFalse(controller.status.closed)
        self.assertTrue(authority_transport.close())
        self.assertTrue(controller.close())

    def test_close_succeeds_after_borrowed_components_were_closed(self) -> None:
        """Runtimeが先にcomponentを閉じてもCoordinator.closeは成功する。"""

        coordinator, _tracker, _client, _published, _applied = self._make("peer-local")
        authority_transport = coordinator._authority_transport  # noqa: SLF001
        controller = coordinator._controller  # noqa: SLF001
        self.assertTrue(authority_transport.close())
        self.assertTrue(controller.close())
        self.assertTrue(coordinator.close())
        self.assertTrue(coordinator.status.closed)

    def test_observer_baseline_and_owner_close(self) -> None:
        """baseline観測、owner thread制限、closeの冪等性を検証する。"""

        coordinator, _tracker, _client, _published, _applied = self._make("peer-local")
        coordinator.observe_authoritative_snapshot(_snapshot("observed"))
        errors: list[BaseException] = []

        def call_from_worker() -> None:
            try:
                coordinator.handle_host_event(_event("worker"))
            except BaseException as error:
                errors.append(error)

        worker = threading.Thread(target=call_from_worker)
        worker.start()
        worker.join()
        self.assertIsInstance(errors[0], PlaybackHandoffThreadError)
        self.assertTrue(coordinator.close())
        self.assertFalse(coordinator.close())
        self.assertTrue(coordinator.status.closed)


if __name__ == "__main__":
    unittest.main()
