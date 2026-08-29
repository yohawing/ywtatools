"""Playback default bootstrap consumerの契約を検証する。"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from ywta_link import (
    AuthorityHandoffAccepted,
    Envelope,
    Frame,
    PlaybackBootstrapConfig,
    PlaybackBootstrapError,
    PlaybackHostRange,
    PlaybackHostSnapshot,
    RationalRate,
    bootstrap_playback_session,
)
from ywta_link.authority import AUTHORITY_ACCEPTED_SCHEMA, AUTHORITY_SNAPSHOT_SCHEMA
from ywta_link.playback_bootstrap import BROKER_PEER_ID
from ywta_link.registry import SLOT_DESCRIPTOR_SCHEMA


class _Client:
    def __init__(
        self,
        peer_id: str,
        frames: list[Frame],
        request_ids: list[str],
        *,
        join_result: object = "join",
        subscribe_result: object = "subscribe",
        fail_close: bool = False,
    ) -> None:
        self.peer_id = peer_id
        self.frames = list(frames)
        self.request_ids = list(request_ids)
        self.calls: list[tuple[object, ...]] = []
        self.closed = 0
        self.join_result = join_result
        self.subscribe_result = subscribe_result
        self.fail_close = fail_close

    def join(self, room: str) -> str:
        self.calls.append(("join", room))
        return self.join_result  # type: ignore[return-value]

    def request(self, room: str, target: str, **kwargs: object) -> str:
        self.calls.append(("request", room, target, kwargs))
        return self.request_ids.pop(0)

    def subscribe(self, room: str, topic: str) -> str:
        self.calls.append(("subscribe", room, topic))
        return self.subscribe_result  # type: ignore[return-value]

    def unsubscribe(self, room: str, topic: str) -> str:
        self.calls.append(("unsubscribe", room, topic))
        return "unsubscribe"

    def receive(self, timeout: float | None = None) -> Frame:
        self.calls.append(("receive", timeout))
        if not self.frames:
            raise TimeoutError("empty")
        return self.frames.pop(0)

    def publish(self, *args: object, **kwargs: object) -> str:
        self.calls.append(("publish", args, kwargs))
        return "publish"

    def response(self, *args: object, **kwargs: object) -> str:
        self.calls.append(("response", args, kwargs))
        return "response"

    def close(self) -> None:
        self.closed += 1
        if self.fail_close:
            raise RuntimeError("close failed")


class _Host:
    def __init__(self, _callback: object) -> None:
        self.applied: list[PlaybackHostSnapshot] = []
        self.initial = PlaybackHostSnapshot("paused", 0, PlaybackHostRange(0, 24), 1.0, "forward", "once", "frames", "baseline")

    def snapshot(self) -> PlaybackHostSnapshot:
        return self.initial

    def apply(self, snapshot: PlaybackHostSnapshot) -> None:
        self.applied.append(snapshot)


class _Lifecycle:
    def __init__(self, _host: object, _runtime: object) -> None:
        self.started = False

    def start(self) -> bool:
        self.started = True
        return True

    def close(self) -> bool:
        return True


def _config(**values: object) -> PlaybackBootstrapConfig:
    data: dict[str, object] = {
        "application_id": "maya",
        "application": "Maya",
        "application_version": "2024",
        "plugin_version": "0.1.0",
        "host_unit_rate": RationalRate(24, 1),
        "time_unit": "frames",
    }
    data.update(values)
    return PlaybackBootstrapConfig(**data)  # type: ignore[arg-type]


def _frame(
    *,
    message_id: str,
    message_type: str,
    sender: str,
    target: str | None,
    room: str,
    correlation_id: str | None,
    schema: str,
    body: object,
    topic: str | None = None,
) -> Frame:
    return Frame(
        Envelope(
            1,
            message_id,
            message_type,
            sender,
            room=room,
            target=target,
            topic=topic,
            correlation_id=correlation_id,
            schema=schema,
            body=body,
        )
    )


def _existing_slot_client(
    peer_id: str,
    config: PlaybackBootstrapConfig,
    session_id: str,
    state_peer: str,
    accepted: list[tuple[AuthorityHandoffAccepted, str]],
    *,
    snapshot_authority: str,
    snapshot_revision: int,
) -> _Client:
    """既存slotのdescriptor、Accepted列、snapshotを順に返すClientを作る。"""

    descriptor = {
        "slot_id": config.slot_id,
        "session_id": session_id,
        "initial_authority": state_peer,
        "metadata": config.slot_metadata,
        "created": False,
        "state_peer": state_peer,
    }
    frames = [
        _frame(
            message_id="descriptor",
            message_type="response",
            sender=BROKER_PEER_ID,
            target=peer_id,
            room=config.room,
            correlation_id="slot",
            schema=SLOT_DESCRIPTOR_SCHEMA,
            body=descriptor,
        )
    ]
    frames.extend(
        _frame(
            message_id=f"accepted-{index}",
            message_type="publish",
            sender=payload.current_authority,
            target=None,
            room=config.room,
            correlation_id=correlation_id,
            schema=AUTHORITY_ACCEPTED_SCHEMA,
            topic=f"sync/{session_id}/control",
            body=payload.to_dict(),
        )
        for index, (payload, correlation_id) in enumerate(accepted)
    )
    frames.append(
        _frame(
            message_id="snapshot",
            message_type="response",
            sender=state_peer,
            target=peer_id,
            room=config.room,
            correlation_id="snapshot",
            schema=AUTHORITY_SNAPSHOT_SCHEMA,
            body={
                "session_id": session_id,
                "channel_id": config.channel_id,
                "authority": snapshot_authority,
                "authority_revision": snapshot_revision,
            },
        )
    )
    return _Client(peer_id, frames, ["slot", "snapshot"])


class PlaybackBootstrapTest(unittest.TestCase):
    def test_config_derives_exact_ticks_and_presence(self) -> None:
        config = _config(host_unit_rate=RationalRate(24000, 1001))
        self.assertEqual(config.ticks_per_host_unit, 5005)
        presence = config.presence("maya:peer")
        self.assertEqual(presence.capabilities, ("playback.apply.v1", "playback.read.v1", "sync.authority.v1"))
        self.assertEqual(config.slot_metadata["wire_timebase"], {"rate_num": 120000, "rate_den": 1})

    def test_config_rejects_non_divisible_host_rate(self) -> None:
        with self.assertRaisesRegex(PlaybackBootstrapError, "divide"):
            _config(host_unit_rate=RationalRate(23, 1))

    def test_join_and_subscribe_require_message_ids(self) -> None:
        config = _config(max_attempts=1)

        def join_factory(peer: str, _presence: object) -> _Client:
            return _Client(peer, [], ["slot"], join_result="")

        with self.assertRaises(PlaybackBootstrapError):
            bootstrap_playback_session(config, _Host, _Lifecycle, join_factory)

        state_peer = "blender:peer"
        descriptor = {
            "slot_id": config.slot_id,
            "session_id": "session-subscribe-id",
            "initial_authority": state_peer,
            "metadata": config.slot_metadata,
            "created": False,
            "state_peer": state_peer,
        }

        def subscribe_factory(peer: str, _presence: object) -> _Client:
            return _Client(
                peer,
                [
                    _frame(
                        message_id="descriptor",
                        message_type="response",
                        sender="ywta-link:broker",
                        target=peer,
                        room=config.room,
                        correlation_id="slot",
                        schema="ywta.session.slot.descriptor.v1",
                        body=descriptor,
                    )
                ],
                ["slot", "snapshot"],
                subscribe_result="",
            )

        with self.assertRaises(PlaybackBootstrapError):
            bootstrap_playback_session(config, _Host, _Lifecycle, subscribe_factory)

    def test_descriptor_metadata_requires_typed_exact_contract(self) -> None:
        config = _config(max_attempts=1)

        def connect(peer: str, _presence: object) -> _Client:
            metadata = {**config.slot_metadata, "contract_version": True}
            descriptor = {
                "slot_id": config.slot_id,
                "session_id": "session-001",
                "initial_authority": peer,
                "metadata": metadata,
                "created": True,
                "state_peer": peer,
            }
            return _Client(
                peer,
                [
                    _frame(
                        message_id="descriptor",
                        message_type="response",
                        sender="ywta-link:broker",
                        target=peer,
                        room=config.room,
                        correlation_id="slot",
                        schema="ywta.session.slot.descriptor.v1",
                        body=descriptor,
                    )
                ],
                ["join", "slot"],
            )

        with self.assertRaises(PlaybackBootstrapError):
            bootstrap_playback_session(config, _Host, _Lifecycle, connect)

    def test_created_slot_composes_unstarted_session(self) -> None:
        peer = "maya:peer"
        config = _config()
        descriptor = {
            "slot_id": config.slot_id,
            "session_id": "session-001",
            "initial_authority": peer,
            "metadata": config.slot_metadata,
            "created": True,
            "state_peer": peer,
        }
        client = _Client(
            peer,
            [
                _frame(
                    message_id="descriptor",
                    message_type="response",
                    sender="ywta-link:broker",
                    target=peer,
                    room="default",
                    correlation_id="slot-request",
                    schema="ywta.session.slot.descriptor.v1",
                    body=descriptor,
                )
            ],
            ["slot-request"],
        )
        peer_ids: list[str] = []

        def connect(peer_id: str, _presence: object) -> _Client:
            peer_ids.append(peer_id)
            client.peer_id = peer_id
            client.frames[0] = _frame(
                message_id="descriptor",
                message_type="response",
                sender="ywta-link:broker",
                target=peer_id,
                room="default",
                correlation_id="slot-request",
                schema="ywta.session.slot.descriptor.v1",
                body={**descriptor, "initial_authority": peer_id, "state_peer": peer_id},
            )
            return client

        session = bootstrap_playback_session(_config(), _Host, _Lifecycle, connect)
        self.assertTrue(peer_ids[0].startswith("maya:"))
        self.assertEqual(session.authority_tracker.state_for("playback").authority, peer_ids[0])
        session.close()

    def test_existing_slot_subscribes_before_snapshot_and_reconciles_chain(self) -> None:
        config = _config()
        peer = "maya:peer"
        state_peer = "blender:peer"
        descriptor = {
            "slot_id": config.slot_id,
            "session_id": "session-001",
            "initial_authority": state_peer,
            "metadata": config.slot_metadata,
            "created": False,
            "state_peer": state_peer,
        }
        accepted = AuthorityHandoffAccepted("session-001", "playback", state_peer, peer, 0, 1, "change-001")
        frames = [
            _frame(
                message_id="descriptor",
                message_type="response",
                sender="ywta-link:broker",
                target=peer,
                room="default",
                correlation_id="slot-request",
                schema="ywta.session.slot.descriptor.v1",
                body=descriptor,
            ),
            _frame(
                message_id="accepted",
                message_type="publish",
                sender=state_peer,
                target=None,
                room="default",
                correlation_id="handoff",
                schema=AUTHORITY_ACCEPTED_SCHEMA,
                topic="sync/session-001/control",
                body=accepted.to_dict(),
            ),
            _frame(
                message_id="snapshot",
                message_type="response",
                sender=state_peer,
                target=peer,
                room="default",
                correlation_id="snapshot-request",
                schema=AUTHORITY_SNAPSHOT_SCHEMA,
                body={"session_id": "session-001", "channel_id": "playback", "authority": state_peer, "authority_revision": 0},
            ),
        ]
        client = _Client(peer, frames, ["slot-request", "snapshot-request"])

        def connect(peer_id: str, _presence: object) -> _Client:
            client.peer_id = peer_id
            client.frames[0] = _frame(
                message_id="descriptor",
                message_type="response",
                sender="ywta-link:broker",
                target=peer_id,
                room="default",
                correlation_id="slot-request",
                schema="ywta.session.slot.descriptor.v1",
                body=descriptor,
            )
            client.frames[1] = _frame(
                message_id="accepted",
                message_type="publish",
                sender=state_peer,
                target=None,
                room="default",
                correlation_id="handoff",
                schema=AUTHORITY_ACCEPTED_SCHEMA,
                topic="sync/session-001/control",
                body=accepted.to_dict(),
            )
            client.frames[2] = _frame(
                message_id="snapshot",
                message_type="response",
                sender=state_peer,
                target=peer_id,
                room="default",
                correlation_id="snapshot-request",
                schema=AUTHORITY_SNAPSHOT_SCHEMA,
                body={"session_id": "session-001", "channel_id": "playback", "authority": state_peer, "authority_revision": 0},
            )
            return client

        session = bootstrap_playback_session(config, _Host, _Lifecycle, connect)
        self.assertEqual(session.authority_tracker.state_for("playback").authority, peer)
        self.assertEqual(session.authority_tracker.state_for("playback").revision, 1)
        subscribe_index = next(
            index for index, call in enumerate(client.calls) if call[:3] == ("subscribe", "default", "sync/session-001/control")
        )
        snapshot_index = next(
            index for index, call in enumerate(client.calls) if call[0] == "request" and call[2] == state_peer
        )
        self.assertLess(subscribe_index, snapshot_index)
        session.close()

    def test_existing_slot_retries_after_gap(self) -> None:
        config = _config(max_attempts=2)
        clients: list[_Client] = []

        def connect(peer: str, _presence: object) -> _Client:
            descriptor = {
                "slot_id": config.slot_id,
                "session_id": "session-001",
                "initial_authority": "blender:peer",
                "metadata": config.slot_metadata,
                "created": False,
                "state_peer": "blender:peer",
            }
            if not clients:
                accepted = AuthorityHandoffAccepted("session-001", "playback", "blender:peer", peer, 1, 2, "change")
                frames = [
                    _frame(
                        message_id="descriptor",
                        message_type="response",
                        sender="ywta-link:broker",
                        target=peer,
                        room="default",
                        correlation_id="slot",
                        schema="ywta.session.slot.descriptor.v1",
                        body=descriptor,
                    ),
                    _frame(
                        message_id="accepted",
                        message_type="publish",
                        sender="blender:peer",
                        target=None,
                        room="default",
                        correlation_id="handoff",
                        schema=AUTHORITY_ACCEPTED_SCHEMA,
                        topic="sync/session-001/control",
                        body=accepted.to_dict(),
                    ),
                    _frame(
                        message_id="snapshot",
                        message_type="response",
                        sender="blender:peer",
                        target=peer,
                        room="default",
                        correlation_id="snap",
                        schema=AUTHORITY_SNAPSHOT_SCHEMA,
                        body={
                            "session_id": "session-001",
                            "channel_id": "playback",
                            "authority": "blender:peer",
                            "authority_revision": 0,
                        },
                    ),
                ]
            else:
                frames = []
            client = _Client(peer, frames, ["slot", "snap"])
            clients.append(client)
            return client

        with self.assertRaises(PlaybackBootstrapError):
            bootstrap_playback_session(config, _Host, _Lifecycle, connect)
        self.assertEqual(len(clients), 2)
        self.assertEqual(clients[0].closed, 1)
        self.assertEqual(clients[1].closed, 1)
        self.assertNotEqual(clients[0].peer_id, clients[1].peer_id)

    def test_snapshot_stale_revision_aborts_without_proof(self) -> None:
        config = _config(max_attempts=1)
        state_peer = "blender:peer"

        def connect(peer: str, _presence: object) -> _Client:
            stale = AuthorityHandoffAccepted("session-stale", "playback", state_peer, "maya:other", 0, 1, "stale")
            return _existing_slot_client(
                peer,
                config,
                "session-stale",
                state_peer,
                [(stale, "handoff")],
                snapshot_authority="maya:other",
                snapshot_revision=2,
            )

        with self.assertRaises(PlaybackBootstrapError):
            bootstrap_playback_session(config, _Host, _Lifecycle, connect)

    def test_snapshot_equal_revision_and_consecutive_chain_succeed(self) -> None:
        config = _config(max_attempts=1)
        state_peer = "blender:peer"
        final_peer = "unity:final"

        def connect(peer: str, _presence: object) -> _Client:
            equal = AuthorityHandoffAccepted("session-chain", "playback", "maya:old", state_peer, 0, 1, "equal")
            chained = AuthorityHandoffAccepted("session-chain", "playback", state_peer, final_peer, 1, 2, "chain")
            return _existing_slot_client(
                peer,
                config,
                "session-chain",
                state_peer,
                [
                    (equal, "equal-correlation"),
                    (equal, "equal-correlation"),
                    (chained, "chain-correlation"),
                ],
                snapshot_authority=state_peer,
                snapshot_revision=1,
            )

        session = bootstrap_playback_session(config, _Host, _Lifecycle, connect)
        state = session.authority_tracker.state_for("playback")
        self.assertEqual((state.authority, state.revision), (final_peer, 2))
        session.close()

    def test_snapshot_subsumes_complete_buffered_prefix(self) -> None:
        config = _config(max_attempts=1)
        state_peer = "maya:a"
        middle_peer = "blender:b"
        final_peer = "unity:c"

        def connect(peer: str, _presence: object) -> _Client:
            first = AuthorityHandoffAccepted("session-prefix", "playback", state_peer, middle_peer, 0, 1, "first")
            second = AuthorityHandoffAccepted("session-prefix", "playback", middle_peer, final_peer, 1, 2, "second")
            return _existing_slot_client(
                peer,
                config,
                "session-prefix",
                state_peer,
                [(first, "first-correlation"), (second, "second-correlation")],
                snapshot_authority=final_peer,
                snapshot_revision=2,
            )

        session = bootstrap_playback_session(config, _Host, _Lifecycle, connect)
        state = session.authority_tracker.state_for("playback")
        self.assertEqual((state.authority, state.revision), (final_peer, 2))
        session.close()

    def test_buffered_chain_authority_mismatch_is_rejected(self) -> None:
        config = _config(max_attempts=1)
        state_peer = "maya:a"

        def connect(peer: str, _presence: object) -> _Client:
            first = AuthorityHandoffAccepted("session-mismatch", "playback", state_peer, "blender:b", 0, 1, "first")
            mismatched = AuthorityHandoffAccepted("session-mismatch", "playback", "maya:other", "unity:c", 1, 2, "second")
            return _existing_slot_client(
                peer,
                config,
                "session-mismatch",
                state_peer,
                [(first, "first-correlation"), (mismatched, "second-correlation")],
                snapshot_authority="blender:b",
                snapshot_revision=1,
            )

        with self.assertRaises(PlaybackBootstrapError):
            bootstrap_playback_session(config, _Host, _Lifecycle, connect)

    def test_equal_revision_conflict_is_rejected(self) -> None:
        config = _config(max_attempts=1)
        state_peer = "blender:peer"
        variants = (
            (AuthorityHandoffAccepted("session-conflict", "playback", "maya:other", state_peer, 0, 1, "change"), "correlation"),
            (
                AuthorityHandoffAccepted("session-conflict", "playback", "maya:old", state_peer, 0, 1, "other-change"),
                "correlation",
            ),
            (
                AuthorityHandoffAccepted("session-conflict", "playback", "maya:old", state_peer, 0, 1, "change"),
                "other-correlation",
            ),
        )
        base = AuthorityHandoffAccepted("session-conflict", "playback", "maya:old", state_peer, 0, 1, "change")
        for conflict, correlation in variants:
            with self.subTest(conflict=conflict, correlation=correlation):

                def connect(peer: str, _presence: object, conflict=conflict, correlation=correlation) -> _Client:
                    return _existing_slot_client(
                        peer,
                        config,
                        "session-conflict",
                        state_peer,
                        [
                            (base, "correlation"),
                            (conflict, correlation),
                        ],
                        snapshot_authority=state_peer,
                        snapshot_revision=1,
                    )

                with self.assertRaises(PlaybackBootstrapError):
                    bootstrap_playback_session(config, _Host, _Lifecycle, connect)

    def test_close_failure_stops_retry(self) -> None:
        config = _config(max_attempts=3)
        clients: list[_Client] = []

        def connect(peer: str, _presence: object) -> _Client:
            client = _Client(peer, [], ["slot"], join_result="", fail_close=True)
            clients.append(client)
            return client

        with self.assertRaises(PlaybackBootstrapError):
            bootstrap_playback_session(config, _Host, _Lifecycle, connect)
        self.assertEqual(len(clients), 1)
        self.assertEqual(clients[0].closed, 1)

    def test_bootstrap_uses_finite_overall_deadline(self) -> None:
        config = _config(max_attempts=1, bootstrap_timeout=1.0)
        clients: list[_Client] = []

        def connect(peer: str, _presence: object) -> _Client:
            client = _Client(peer, [], ["slot"])
            clients.append(client)
            return client

        with patch("ywta_link.playback_bootstrap.time.monotonic", side_effect=(0.0, 2.0)):
            with self.assertRaisesRegex(PlaybackBootstrapError, "timed out"):
                bootstrap_playback_session(config, _Host, _Lifecycle, connect)
        self.assertEqual(clients[0].closed, 1)

    def test_composition_failure_does_not_retry_and_closes_once(self) -> None:
        config = _config(max_attempts=3)
        clients: list[_Client] = []

        def connect(peer: str, _presence: object) -> _Client:
            descriptor = {
                "slot_id": config.slot_id,
                "session_id": "session-compose",
                "initial_authority": peer,
                "metadata": config.slot_metadata,
                "created": True,
                "state_peer": peer,
            }
            client = _Client(
                peer,
                [
                    _frame(
                        message_id="descriptor",
                        message_type="response",
                        sender="ywta-link:broker",
                        target=peer,
                        room=config.room,
                        correlation_id="slot",
                        schema="ywta.session.slot.descriptor.v1",
                        body=descriptor,
                    )
                ],
                ["slot"],
            )
            clients.append(client)
            return client

        def fail_host(_callback: object) -> object:
            raise RuntimeError("host construction")

        with self.assertRaisesRegex(RuntimeError, "host construction"):
            bootstrap_playback_session(config, fail_host, _Lifecycle, connect)
        self.assertEqual(len(clients), 1)
        self.assertEqual(clients[0].closed, 1)

    def test_accept_buffer_is_bounded(self) -> None:
        config = _config(max_attempts=1)
        state_peer = "blender:peer"

        def connect(peer: str, _presence: object) -> _Client:
            descriptor = {
                "slot_id": config.slot_id,
                "session_id": "session-buffer",
                "initial_authority": state_peer,
                "metadata": config.slot_metadata,
                "created": False,
                "state_peer": state_peer,
            }
            accepted = AuthorityHandoffAccepted("session-buffer", "playback", state_peer, peer, 0, 1, "buffer")
            frames = [
                _frame(
                    message_id="descriptor",
                    message_type="response",
                    sender="ywta-link:broker",
                    target=peer,
                    room=config.room,
                    correlation_id="slot",
                    schema="ywta.session.slot.descriptor.v1",
                    body=descriptor,
                )
            ]
            frames.extend(
                _frame(
                    message_id=f"accepted-{index}",
                    message_type="publish",
                    sender=state_peer,
                    target=None,
                    room=config.room,
                    correlation_id=f"correlation-{index}",
                    schema=AUTHORITY_ACCEPTED_SCHEMA,
                    topic="sync/session-buffer/control",
                    body=accepted.to_dict(),
                )
                for index in range(257)
            )
            return _Client(peer, frames, ["slot", "snapshot"])

        with self.assertRaises(PlaybackBootstrapError):
            bootstrap_playback_session(config, _Host, _Lifecycle, connect)


if __name__ == "__main__":
    unittest.main()
