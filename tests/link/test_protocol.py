"""YWTA Link v1 protocol foundationのGolden JSON検証。"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from ywta_link.contract import NegotiationResult, SyncContract
from ywta_link.envelope import Envelope
from ywta_link.errors import (
    AuthorityViolation,
    ContractValidationError,
    EnvelopeValidationError,
    InvalidStateTransition,
    StaleRevision,
)
from ywta_link.session import ChannelRevisionTracker, SessionState, SyncSession

_FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "protocol" / "ywta-link" / "v1"


def _fixture(category: str, name: str) -> str:
    """Golden JSON fixtureをUTF-8文字列として読む。"""

    return (_FIXTURE_ROOT / category / name).read_text(encoding="utf-8")


class EnvelopeTest(unittest.TestCase):
    """共通Envelopeの検証を行う。"""

    def test_valid_fixture_preserves_unknown_field(self) -> None:
        """登録済みSync schemaと未知Fieldをdecode/encodeできる。"""

        envelope = Envelope.decode(_fixture("valid", "envelope-publish.json"))

        self.assertEqual(envelope.schema, "ywta.sync.preview.v1")
        self.assertEqual(envelope.extra["fixture_note"], "未知Fieldは転送時に保持する")
        self.assertEqual(json.loads(envelope.encode()), envelope.to_dict())

    def test_missing_required_field_fails_closed(self) -> None:
        """必須senderを欠くEnvelopeを拒否する。"""

        with self.assertRaises(EnvelopeValidationError):
            Envelope.decode(_fixture("invalid", "envelope-missing-sender.json"))

    def test_response_requires_target_and_correlation_id(self) -> None:
        """Responseは宛先と元RequestのIDなしに送れない。"""

        with self.assertRaises(EnvelopeValidationError):
            Envelope.from_dict(
                {
                    "protocol_version": 1,
                    "message_id": "response-001",
                    "type": "response",
                    "sender": "maya:peer-001",
                    "room": "shot-010",
                    "target": "blender:peer-001",
                }
            )

    def test_target_message_requires_room_boundary(self) -> None:
        """Target送信もRoomを越えて配送しない契約にする。"""

        with self.assertRaises(EnvelopeValidationError):
            Envelope.from_dict(
                {
                    "protocol_version": 1,
                    "message_id": "request-001",
                    "type": "request",
                    "sender": "blender:peer-001",
                    "target": "maya:peer-001",
                }
            )

    def test_subscription_requires_topic(self) -> None:
        """Topic購読はRoomだけでなくTopic名も要求する。"""

        with self.assertRaises(EnvelopeValidationError):
            Envelope.from_dict(
                {
                    "protocol_version": 1,
                    "message_id": "subscribe-001",
                    "type": "subscribe",
                    "sender": "maya:peer-001",
                    "room": "shot-010",
                }
            )

    def test_envelope_routes_unknown_versioned_schema(self) -> None:
        """Brokerが解釈しない拡張Schemaはversion付きならEnvelopeで運べる。"""

        envelope = Envelope.from_dict(
            {
                "protocol_version": 1,
                "message_id": "material-001",
                "type": "publish",
                "sender": "blender:peer-001",
                "room": "character-a",
                "schema": "studio.material.preview.v1",
            }
        )
        self.assertEqual(envelope.schema, "studio.material.preview.v1")

        with self.assertRaises(EnvelopeValidationError):
            Envelope.from_dict(
                {
                    "protocol_version": 1,
                    "message_id": "material-002",
                    "type": "publish",
                    "sender": "blender:peer-001",
                    "room": "character-a",
                    "schema": "studio.material.preview",
                }
            )


class ContractTest(unittest.TestCase):
    """Sync ContractとNegotiation結果の検証を行う。"""

    def test_valid_fixture_round_trips(self) -> None:
        """Camera preview Contractを決定的に変換できる。"""

        contract = SyncContract.decode(_fixture("valid", "contract-camera-preview.json"))

        self.assertEqual(contract.channels[0].channel_id, "main-camera")
        self.assertEqual(json.loads(contract.encode()), contract.to_dict())

    def test_unknown_schema_fails_closed(self) -> None:
        """未登録SchemaをContractに含められない。"""

        with self.assertRaises(ContractValidationError):
            SyncContract.decode(_fixture("invalid", "contract-unknown-schema.json"))

    def test_duplicate_channel_fails_closed(self) -> None:
        """同一Channel IDを複数回宣言できない。"""

        with self.assertRaises(ContractValidationError):
            SyncContract.decode(_fixture("invalid", "contract-duplicate-channel.json"))

    def test_script_field_fails_closed(self) -> None:
        """Contractは実行可能なFieldを受け付けない。"""

        with self.assertRaises(ContractValidationError):
            SyncContract.decode(_fixture("invalid", "contract-script-field.json"))

    def test_snapshot_mode_is_supported(self) -> None:
        """安全なPreviewを持たないAdapterはsnapshot applyを選べる。"""

        payload = json.loads(_fixture("valid", "contract-camera-preview.json"))
        payload["channels"][0]["mode"] = "snapshot"

        self.assertEqual(SyncContract.from_dict(payload).channels[0].mode, "snapshot")

    def test_policy_arrays_fail_with_validation_error(self) -> None:
        """列挙Fieldへ配列を与えても内部TypeErrorを漏らさない。"""

        payload = json.loads(_fixture("valid", "contract-camera-preview.json"))
        payload["channels"][0]["mode"] = []
        with self.assertRaises(ContractValidationError):
            SyncContract.from_dict(payload)

        payload = json.loads(_fixture("valid", "contract-camera-preview.json"))
        payload["close_policy"] = []
        with self.assertRaises(ContractValidationError):
            SyncContract.from_dict(payload)

    def test_negotiation_status_is_limited(self) -> None:
        """仕様で定義した三つの判定だけを受け入れる。"""

        for status in ("exact", "approximated", "unsupported"):
            self.assertEqual(NegotiationResult("main-camera", status).status, status)
        with self.assertRaises(ContractValidationError):
            NegotiationResult("main-camera", "partial")


class SessionTest(unittest.TestCase):
    """状態遷移とAuthority/revision検証を行う。"""

    def setUp(self) -> None:
        """有効なContractから各検証対象を作る。"""

        self.contract = SyncContract.decode(_fixture("valid", "contract-camera-preview.json"))

    def test_state_machine_allows_declared_path(self) -> None:
        """DraftからClosedまでの正規経路だけを許可する。"""

        session = SyncSession(self.contract)
        for state in (
            SessionState.NEGOTIATING,
            SessionState.ACTIVE,
            SessionState.CLOSING,
            SessionState.CLOSED,
        ):
            self.assertEqual(session.transition(state), state)

        with self.assertRaises(InvalidStateTransition):
            session.transition(SessionState.ACTIVE)

    def test_state_machine_allows_failure_only_before_completion(self) -> None:
        """Negotiating、Active、ClosingからだけFailedへ遷移できる。"""

        session = SyncSession(self.contract)
        with self.assertRaises(InvalidStateTransition):
            session.transition(SessionState.FAILED)
        session.transition(SessionState.NEGOTIATING)
        self.assertEqual(session.transition(SessionState.FAILED), SessionState.FAILED)

    def test_revision_tracker_rejects_non_authority_and_stale_updates(self) -> None:
        """Authority以外と重複revisionをAdapter到達前に拒否する。"""

        tracker = ChannelRevisionTracker(self.contract)
        self.assertEqual(tracker.accept("main-camera", "blender:peer-001", 8), 8)
        with self.assertRaises(AuthorityViolation):
            tracker.accept("main-camera", "maya:peer-001", 9)
        with self.assertRaises(StaleRevision):
            tracker.accept("main-camera", "blender:peer-001", 8)


if __name__ == "__main__":
    unittest.main()
