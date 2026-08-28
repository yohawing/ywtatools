"""YWTA Link Authority handoffのwire contractと状態競合を検証する。"""

from __future__ import annotations

import json
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from ywta_link import (
    AUTHORITY_ACCEPTED_FIELDS,
    AUTHORITY_ACCEPTED_SCHEMA,
    AUTHORITY_REJECTED_FIELDS,
    AUTHORITY_REJECTED_SCHEMA,
    AUTHORITY_REQUEST_FIELDS,
    AUTHORITY_REQUEST_SCHEMA,
    AuthorityHandoffAccepted,
    AuthorityHandoffRejected,
    AuthorityHandoffRequest,
    AuthorityHandoffTracker,
    AuthorityValidationError,
)
from ywta_link.errors import AuthorityViolation, StaleRevision
from ywta_link.envelope import Envelope
from ywta_link.registry import DEFAULT_REGISTRY

_FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "protocol" / "ywta-link" / "v1" / "valid"


def _fixture(name: str) -> str:
    """Authority Golden JSONをUTF-8文字列として読む。"""

    return (_FIXTURE_ROOT / name).read_text(encoding="utf-8")


class AuthorityPayloadTest(unittest.TestCase):
    """Authority handoff payloadの型とstrict validationを検証する。"""

    def test_golden_fixtures_round_trip_and_registry_fields_match(self) -> None:
        """3種類のGolden JSONをdecode/encodeし、registryとField集合を一致させる。"""

        cases = (
            ("authority-request.json", AuthorityHandoffRequest, AUTHORITY_REQUEST_SCHEMA, AUTHORITY_REQUEST_FIELDS),
            ("authority-accepted.json", AuthorityHandoffAccepted, AUTHORITY_ACCEPTED_SCHEMA, AUTHORITY_ACCEPTED_FIELDS),
            ("authority-rejected.json", AuthorityHandoffRejected, AUTHORITY_REJECTED_SCHEMA, AUTHORITY_REJECTED_FIELDS),
        )
        for filename, payload_type, schema, fields in cases:
            with self.subTest(filename=filename):
                payload = payload_type.decode(_fixture(filename))
                encoded = json.loads(payload.encode())
                self.assertEqual(encoded, payload.to_dict())
                self.assertEqual(set(encoded), fields)
                self.assertEqual(DEFAULT_REGISTRY.require_schema(schema), fields)
                self.assertNotIn("schema", encoded)

        self.assertTrue(DEFAULT_REGISTRY.has_capability("sync.authority.v1"))
        DEFAULT_REGISTRY.require_capability("sync.authority.v1")

    def test_accepted_revision_is_exactly_one_ahead(self) -> None:
        """acceptedはexpected revisionの1つ先以外を拒否する。"""

        payload = json.loads(_fixture("authority-accepted.json"))
        for value in (0, 2, -1, True, "1"):
            payload["new_authority_revision"] = value
            with self.subTest(value=repr(value)):
                with self.assertRaises(AuthorityValidationError):
                    AuthorityHandoffAccepted.from_dict(payload)

    def test_strict_validation_rejects_unknown_missing_and_invalid_values(self) -> None:
        """unknown/missing Field、型違い、空白ID、不正JSONをfail closedする。"""

        for filename, payload_type in (
            ("authority-request.json", AuthorityHandoffRequest),
            ("authority-accepted.json", AuthorityHandoffAccepted),
            ("authority-rejected.json", AuthorityHandoffRejected),
        ):
            base = json.loads(_fixture(filename))
            base["unexpected"] = None
            with self.subTest(filename=filename, mutation="unknown"):
                with self.assertRaises(AuthorityValidationError):
                    payload_type.from_dict(base)

            base = json.loads(_fixture(filename))
            del base["change_id"]
            with self.subTest(filename=filename, mutation="missing"):
                with self.assertRaises(AuthorityValidationError):
                    payload_type.from_dict(base)

            base = json.loads(_fixture(filename))
            base["current_authority"] = " \t"
            with self.subTest(filename=filename, mutation="whitespace"):
                with self.assertRaises(AuthorityValidationError):
                    payload_type.from_dict(base)

            base = json.loads(_fixture(filename))
            base["expected_authority_revision"] = True
            with self.subTest(filename=filename, mutation="bool-revision"):
                with self.assertRaises(AuthorityValidationError):
                    payload_type.from_dict(base)

        with self.assertRaises(AuthorityValidationError):
            AuthorityHandoffRequest.decode(b"{not-json}")
        with self.assertRaises(AuthorityValidationError):
            AuthorityHandoffRequest.decode(b"\xff")
        with self.assertRaises(AuthorityValidationError):
            AuthorityHandoffRequest.from_dict([])  # type: ignore[arg-type]

    def test_payloads_are_immutable_and_output_is_detached(self) -> None:
        """typed payloadがfrozenで、出力dictを変更しても影響しないことを検証する。"""

        request = AuthorityHandoffRequest.decode(_fixture("authority-request.json"))
        output = request.to_dict()
        output["channel_id"] = "other"
        self.assertEqual(request.channel_id, "main-camera")
        with self.assertRaises(FrozenInstanceError):
            request.channel_id = "other"  # type: ignore[misc]


class AuthorityTrackerTest(unittest.TestCase):
    """Authority handoffのstate、競合、権限境界を検証する。"""

    def setUp(self) -> None:
        """2つのChannelを持つ独立なtrackerを作る。"""

        self.tracker = AuthorityHandoffTracker(
            {"timeline": "blender:peer-001", "camera": "maya:peer-001"}, session_id="session-001"
        )

    def test_mapping_tracker_requires_session_id(self) -> None:
        """mappingから作るTrackerはSync Session境界のためsession_idを必須とする。"""

        with self.assertRaises(AuthorityValidationError):
            AuthorityHandoffTracker({"timeline": "blender:peer-001"})

    def _request(self, channel_id: str = "timeline", expected: int = 0) -> AuthorityHandoffRequest:
        """テスト用handoff requestを作る。"""

        return AuthorityHandoffRequest(
            session_id="session-001",
            channel_id=channel_id,
            current_authority="blender:peer-001" if channel_id == "timeline" else "maya:peer-001",
            next_authority="maya:peer-001" if channel_id == "timeline" else "blender:peer-001",
            expected_authority_revision=expected,
            change_id=f"change-{channel_id}-{expected}",
        )

    def test_initial_authority_revision_is_zero_and_content_is_independent(self) -> None:
        """Authority revisionはChannelごとに0開始し、content revisionを共有しない。"""

        self.assertEqual(self.tracker.state_for("timeline").revision, 0)
        self.assertEqual(self.tracker.state_for("camera").revision, 0)

    def test_accept_is_atomic_and_moves_authority_by_one_revision(self) -> None:
        """現在Authorityのacceptがauthority、revision、pendingを一括更新する。"""

        request = self._request()
        self.tracker.request_handoff(request, requester="maya:peer-001", request_message_id="request-001")
        accepted = self.tracker.accept_handoff(
            request, actor="blender:peer-001", correlation_id="request-001"
        )

        self.assertEqual(accepted.new_authority_revision, 1)
        self.assertEqual(self.tracker.state_for("timeline").authority, "maya:peer-001")
        self.assertEqual(self.tracker.state_for("timeline").revision, 1)
        self.assertIsNone(self.tracker.pending_for("timeline"))

    def test_unauthorized_accept_and_reject_do_not_mutate_pending_state(self) -> None:
        """現在Authority以外のaccept/rejectを拒否し、pendingを保持する。"""

        request = self._request()
        self.tracker.request_handoff(request, requester="maya:peer-001", request_message_id="request-001")
        with self.assertRaises(AuthorityViolation):
            self.tracker.accept_handoff(request, actor="maya:peer-001", correlation_id="request-001")
        with self.assertRaises(AuthorityViolation):
            self.tracker.reject_handoff(
                request, actor="maya:peer-001", reason="not allowed", correlation_id="request-001"
            )
        self.assertEqual(self.tracker.pending_for("timeline").request, request)
        self.assertEqual(self.tracker.pending_for("timeline").request_message_id, "request-001")
        self.assertEqual(self.tracker.state_for("timeline").revision, 0)

    def test_reject_preserves_authority_and_revision(self) -> None:
        """rejectはreasonを返してpendingだけを解放し、stateを変更しない。"""

        request = self._request()
        self.tracker.request_handoff(request, requester="maya:peer-001", request_message_id="request-001")
        rejected = self.tracker.reject_handoff(
            request, actor="blender:peer-001", reason="busy", correlation_id="request-001"
        )

        self.assertEqual(rejected.reason, "busy")
        self.assertEqual(self.tracker.state_for("timeline").authority, "blender:peer-001")
        self.assertEqual(self.tracker.state_for("timeline").revision, 0)
        self.assertIsNone(self.tracker.pending_for("timeline"))

    def test_stale_and_concurrent_requests_are_rejected(self) -> None:
        """古いrevisionと同一Channelの同時handoffを受け付けない。"""

        request = self._request()
        self.tracker.request_handoff(request, requester="maya:peer-001", request_message_id="request-001")
        with self.assertRaises(StaleRevision):
            self.tracker.request_handoff(request, requester="maya:peer-001", request_message_id="request-002")

        self.tracker.accept_handoff(request, actor="blender:peer-001", correlation_id="request-001")
        with self.assertRaises(StaleRevision):
            self.tracker.request_handoff(request, requester="maya:peer-001", request_message_id="request-001")

    def test_pending_response_application_keeps_replica_state_safe(self) -> None:
        """response replicaへの適用もpending、authority、revisionを厳密に照合する。"""

        request = self._request()
        self.tracker.request_handoff(request, requester="maya:peer-001", request_message_id="request-001")
        accepted = AuthorityHandoffAccepted(
            session_id=request.session_id,
            channel_id=request.channel_id,
            current_authority=request.current_authority,
            next_authority=request.next_authority,
            expected_authority_revision=0,
            new_authority_revision=1,
            change_id=request.change_id,
        )
        self.tracker.apply_accepted(accepted, actor="blender:peer-001", correlation_id="request-001")
        self.assertEqual(self.tracker.state_for("timeline").authority, "maya:peer-001")
        self.assertEqual(self.tracker.state_for("timeline").revision, 1)

        with self.assertRaises(AuthorityViolation):
            self.tracker.apply_accepted(accepted, actor="blender:peer-001", correlation_id="request-001")

    def test_three_replicas_converge_from_accepted_fanout(self) -> None:
        """Blender/Maya/Unityが同じrequestとaccepted fan-outを観測して同じstateへ収束する。"""

        request = self._request()
        replicas = [
            AuthorityHandoffTracker({"timeline": "blender:peer-001"}, session_id="session-001")
            for _ in range(3)
        ]
        for replica in replicas:
            replica.request_handoff(request, requester="maya:peer-001", request_message_id="request-001")

        accepted = replicas[0].accept_handoff(
            request, actor="blender:peer-001", correlation_id="request-001"
        )
        for replica in replicas[1:]:
            replica.apply_accepted(accepted, actor="blender:peer-001", correlation_id="request-001")

        states = [replica.state_for("timeline") for replica in replicas]
        self.assertEqual(states, [states[0], states[0], states[0]])
        self.assertEqual(states[0].authority, "maya:peer-001")
        self.assertEqual(states[0].revision, 1)

    def test_current_authority_wins_concurrent_requests_and_observers_apply_without_pending(self) -> None:
        """現Authorityが選んだAを3 replicaへfan-outし、B pendingも明示winnerへ収束させる。"""

        authority = AuthorityHandoffTracker({"timeline": "blender:peer-001"}, session_id="session-001")
        maya = AuthorityHandoffTracker({"timeline": "blender:peer-001"}, session_id="session-001")
        unity = AuthorityHandoffTracker({"timeline": "blender:peer-001"}, session_id="session-001")
        observer = AuthorityHandoffTracker({"timeline": "blender:peer-001"}, session_id="session-001")
        request_a = self._request()
        request_b = AuthorityHandoffRequest(
            session_id="session-001",
            channel_id="timeline",
            current_authority="blender:peer-001",
            next_authority="unity:peer-001",
            expected_authority_revision=0,
            change_id="change-timeline-b",
        )

        authority.request_handoff(request_a, requester="maya:peer-001", request_message_id="request-a")
        maya.request_handoff(request_a, requester="maya:peer-001", request_message_id="request-a")
        unity.request_handoff(request_b, requester="unity:peer-001", request_message_id="request-b")
        accepted_a = authority.accept_handoff(
            request_a, actor="blender:peer-001", correlation_id="request-a"
        )

        # Brokerのsender exclusion相当として、発行元Authorityは自分のaccept結果を再適用しない。
        maya.apply_accepted(accepted_a, actor="blender:peer-001", correlation_id="request-a")
        unity.apply_accepted(accepted_a, actor="blender:peer-001", correlation_id="request-a")
        observer.apply_accepted(accepted_a, actor="blender:peer-001", correlation_id="request-a")

        states = [replica.state_for("timeline") for replica in (authority, maya, unity, observer)]
        self.assertEqual(states, [states[0]] * 4)
        self.assertEqual(states[0].authority, "maya:peer-001")
        self.assertEqual(states[0].revision, 1)
        self.assertIsNone(maya.pending_for("timeline"))
        self.assertIsNone(unity.pending_for("timeline"))
        self.assertIsNone(observer.pending_for("timeline"))

        for replica in (authority, maya, unity, observer):
            self.assertEqual(replica.accept_content("timeline", "maya:peer-001", 1), 1)
            with self.subTest(replica=replica):
                with self.assertRaises(AuthorityViolation):
                    replica.accept_content("timeline", "blender:peer-001", 2)

    def test_handoff_control_uses_publish_session_topic_and_request_correlation(self) -> None:
        """handoffのRequest/AcceptedがSession control topicのpublishで相関する。"""

        request = self._request()
        request_envelope = Envelope(
            protocol_version=1,
            message_id="request-001",
            type="request",
            sender="maya:peer-001",
            room="room-001",
            target="blender:peer-001",
            schema=AUTHORITY_REQUEST_SCHEMA,
            body=request.to_dict(),
        )
        accepted_envelope = Envelope(
            protocol_version=1,
            message_id="accepted-001",
            type="publish",
            sender="blender:peer-001",
            room="room-001",
            topic="sync/session-001/control",
            correlation_id=request_envelope.message_id,
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
        )
        accepted_response = Envelope(
            protocol_version=1,
            message_id="accepted-response-001",
            type="response",
            sender="blender:peer-001",
            room="room-001",
            target="maya:peer-001",
            correlation_id=request_envelope.message_id,
            schema=AUTHORITY_ACCEPTED_SCHEMA,
            body=accepted_envelope.body,
        )
        rejected_response = Envelope(
            protocol_version=1,
            message_id="rejected-response-001",
            type="response",
            sender="blender:peer-001",
            room="room-001",
            target="maya:peer-001",
            correlation_id=request_envelope.message_id,
            schema=AUTHORITY_REJECTED_SCHEMA,
            body=AuthorityHandoffRejected(
                session_id=request.session_id,
                channel_id=request.channel_id,
                current_authority=request.current_authority,
                next_authority=request.next_authority,
                expected_authority_revision=0,
                change_id=request.change_id,
                reason="busy",
            ).to_dict(),
        )
        self.assertEqual(request_envelope.type, "request")
        self.assertEqual(request_envelope.target, "blender:peer-001")
        self.assertEqual(accepted_envelope.type, "publish")
        self.assertEqual(accepted_envelope.topic, "sync/session-001/control")
        self.assertEqual(accepted_envelope.correlation_id, request_envelope.message_id)
        self.assertEqual(accepted_response.type, "response")
        self.assertEqual(accepted_response.target, "maya:peer-001")
        self.assertEqual(accepted_response.correlation_id, request_envelope.message_id)
        self.assertEqual(rejected_response.type, "response")
        self.assertIsNone(rejected_response.topic)
        self.assertEqual(rejected_response.correlation_id, request_envelope.message_id)

    def test_correlation_id_must_match_pending_request_message_id(self) -> None:
        """accepted/rejected操作は元Request Envelopeのmessage ID以外を拒否する。"""

        request = self._request()
        self.tracker.request_handoff(request, requester="maya:peer-001", request_message_id="request-001")
        with self.assertRaises(StaleRevision):
            self.tracker.accept_handoff(request, actor="blender:peer-001", correlation_id="request-other")
        with self.assertRaises(StaleRevision):
            self.tracker.reject_handoff(
                request, actor="blender:peer-001", reason="busy", correlation_id="request-other"
            )
        self.assertEqual(self.tracker.pending_for("timeline").request_message_id, "request-001")

    def test_unrelated_rejected_response_does_not_clear_local_pending(self) -> None:
        """Rejected Aは一致するpendingだけを解放し、競合するpending Bを保持する。"""

        request_a = self._request()
        request_b = AuthorityHandoffRequest(
            session_id="session-001",
            channel_id="timeline",
            current_authority="blender:peer-001",
            next_authority="unity:peer-001",
            expected_authority_revision=0,
            change_id="change-timeline-b",
        )
        self.tracker.request_handoff(request_b, requester="unity:peer-001", request_message_id="request-b")
        rejected_a = AuthorityHandoffRejected(
            session_id="session-001",
            channel_id="timeline",
            current_authority="blender:peer-001",
            next_authority="maya:peer-001",
            expected_authority_revision=0,
            change_id=request_a.change_id,
            reason="busy",
        )
        self.tracker.apply_rejected(rejected_a, actor="blender:peer-001", correlation_id="request-a")

        self.assertEqual(self.tracker.pending_for("timeline").request, request_b)
        self.assertEqual(self.tracker.state_for("timeline").authority, "blender:peer-001")
        self.assertEqual(self.tracker.state_for("timeline").revision, 0)

    def test_request_message_id_and_response_correlation_are_required(self) -> None:
        """handoffのtransport identityとresponse correlationの欠落を拒否する。"""

        request = self._request()
        for message_id in ("", " ", None):
            with self.subTest(message_id=repr(message_id)):
                with self.assertRaises(AuthorityValidationError):
                    self.tracker.request_handoff(
                        request,
                        requester="maya:peer-001",
                        request_message_id=message_id,  # type: ignore[arg-type]
                    )

        self.tracker.request_handoff(request, requester="maya:peer-001", request_message_id="request-001")
        with self.assertRaises(AuthorityValidationError):
            self.tracker.accept_handoff(
                request, actor="blender:peer-001", correlation_id=None  # type: ignore[arg-type]
            )

    def test_disconnect_never_auto_promotes(self) -> None:
        """authority切断の観測だけでは別Peerを自動昇格させない。"""

        affected = self.tracker.observe_disconnect("blender:peer-001")
        self.assertEqual(affected, ("timeline",))
        self.assertEqual(self.tracker.state_for("timeline").authority, "blender:peer-001")
        self.assertEqual(self.tracker.state_for("timeline").revision, 0)


if __name__ == "__main__":
    unittest.main()
