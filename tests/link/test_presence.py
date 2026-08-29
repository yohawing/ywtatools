"""Peer Presence/Capability広告の共通契約を検証する。"""

from __future__ import annotations

import json
import socket
import threading
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

from ywta_link.client import LinkClient, LinkClientError
from ywta_link.envelope import Envelope
from ywta_link.frame import Frame
from ywta_link.presence import (
    PEER_HELLO_SCHEMA,
    PRESENCE_MAX_PROTOCOL_VERSION,
    PeerPresence,
    PresenceValidationError,
)

_FIXTURE = Path(__file__).parent / "fixtures" / "peer_hello_v1.json"


def _presence() -> PeerPresence:
    """テスト用の最小で有効なPresenceを返す。"""

    return PeerPresence(
        peer_id="blender:peer-001",
        application="Blender",
        application_version="4.5.0",
        plugin_version="0.1.0",
        protocol_versions=(1,),
        capabilities=("camera.apply.v1", "camera.read.v1", "transform.read.v1"),
    )


class PeerPresenceTest(unittest.TestCase):
    """Presence modelとPython/Rust共有fixtureを検証する。"""

    def test_golden_fixture_decodes_and_round_trips(self) -> None:
        """Rust側と同じfixtureをdecodeし、意味を保ったままencodeする。"""

        presence = PeerPresence.decode(_FIXTURE.read_bytes())
        self.assertEqual(json.loads(presence.encode()), json.loads(_FIXTURE.read_text()))

    def test_model_is_immutable_and_requires_tuples(self) -> None:
        """広告後に配列を変更できないようimmutable型を要求する。"""

        presence = _presence()
        with self.assertRaises(FrozenInstanceError):
            presence.peer_id = "maya:peer-001"  # type: ignore[misc]
        with self.assertRaises(PresenceValidationError):
            PeerPresence(
                peer_id=presence.peer_id,
                application=presence.application,
                application_version=presence.application_version,
                plugin_version=presence.plugin_version,
                protocol_versions=[1],  # type: ignore[arg-type]
                capabilities=presence.capabilities,
            )

    def test_decoder_rejects_unknown_fields_and_invalid_order(self) -> None:
        """未知Field、bool、異種型、未昇順の配列をfail closedで拒否する。"""

        value = json.loads(_FIXTURE.read_text())
        value["unexpected"] = True
        with self.assertRaises(PresenceValidationError):
            PeerPresence.from_dict(value)
        value = json.loads(_FIXTURE.read_text())
        value["protocol_versions"] = [True]
        with self.assertRaises(PresenceValidationError):
            PeerPresence.from_dict(value)
        value = json.loads(_FIXTURE.read_text())
        value["capabilities"] = ["camera.read.v1", "camera.apply.v1"]
        with self.assertRaises(PresenceValidationError):
            PeerPresence.from_dict(value)
        for capabilities in (["camera.read.v1", 1], ["camera.read.v1", []], [1]):
            value = json.loads(_FIXTURE.read_text())
            value["capabilities"] = capabilities
            with self.subTest(capabilities=capabilities):
                with self.assertRaises(PresenceValidationError):
                    PeerPresence.from_dict(value)

    def test_decoder_rejects_missing_v1_and_oversized_metadata(self) -> None:
        """v1未対応、範囲外version、上限超過、未versioned IDを拒否する。"""

        base = json.loads(_FIXTURE.read_text())
        for field, replacement in (
            ("protocol_versions", [2]),
            ("protocol_versions", [0, 1]),
            ("protocol_versions", [1, PRESENCE_MAX_PROTOCOL_VERSION + 1]),
            ("capabilities", ["camera.read"]),
            ("application", "x" * 257),
            ("capabilities", ["x.v1"] * 129),
        ):
            value = dict(base)
            value[field] = replacement
            with self.subTest(field=field, replacement=str(replacement)[:20]):
                with self.assertRaises(PresenceValidationError):
                    PeerPresence.from_dict(value)

    def test_decoder_accepts_protocol_upper_bound_and_empty_capabilities(self) -> None:
        """Protocol versionの上限とCapability 0件を有効として扱う。"""

        value = json.loads(_FIXTURE.read_text())
        value["protocol_versions"] = [1, PRESENCE_MAX_PROTOCOL_VERSION]
        value["capabilities"] = []
        presence = PeerPresence.from_dict(value)
        self.assertEqual(presence.protocol_versions, (1, PRESENCE_MAX_PROTOCOL_VERSION))
        self.assertEqual(presence.capabilities, ())

    def test_invalid_utf8_strings_are_rejected_before_socket_creation(self) -> None:
        """lone surrogateを構築時とconnect前の両方で拒否する。"""

        for field in (
            "peer_id",
            "application",
            "application_version",
            "plugin_version",
        ):
            with self.subTest(field=field):
                values = _presence().__dict__.copy()
                values[field] = "bad\ud800"
                with self.assertRaises(PresenceValidationError):
                    PeerPresence(**values)

        values = _presence().__dict__.copy()
        values["capabilities"] = ("bad\ud800.v1",)
        with self.assertRaises(PresenceValidationError):
            PeerPresence(**values)

        tampered = _presence()
        object.__setattr__(tampered, "application", "bad\ud800")
        client = LinkClient("127.0.0.1:24567", tampered.peer_id, presence=tampered)
        with patch("ywta_link.client._open_loopback_socket") as open_socket:
            with self.assertRaises(PresenceValidationError):
                client.connect()
        open_socket.assert_not_called()


class PeerPresenceClientTest(unittest.TestCase):
    """Client helloと再接続時のPresence広告を検証する。"""

    def test_connect_sends_schema_body_and_runtime_challenge_together(self) -> None:
        """runtime token challengeはPresence schema/bodyと共存する。"""

        client_socket, broker_socket = socket.socketpair()
        self.addCleanup(broker_socket.close)
        client = LinkClient(
            "127.0.0.1:24567",
            "blender:peer-001",
            presence=_presence(),
        )
        self.addCleanup(client.close)
        received: list[Frame] = []

        def respond() -> None:
            hello = Frame.read_from(broker_socket)
            received.append(hello)
            Frame(
                Envelope(
                    protocol_version=1,
                    message_id="broker-ack-001",
                    type="hello",
                    sender="ywta-link:broker",
                    correlation_id=hello.envelope.message_id,
                    extra={
                        "ywta_runtime_challenge": hello.envelope.extra["ywta_runtime_challenge"],
                        "ywta_runtime_token": "runtime-token-001",
                    },
                ),
                b"",
            ).write_to(broker_socket)

        responder = threading.Thread(target=respond)
        responder.start()
        with patch("ywta_link.client._open_loopback_socket", return_value=client_socket):
            client.connect(timeout=1, expected_runtime_token="runtime-token-001")
        responder.join(timeout=1)

        self.assertFalse(responder.is_alive())
        hello = received[0]
        self.assertEqual(hello.envelope.schema, PEER_HELLO_SCHEMA)
        self.assertEqual(hello.envelope.body, _presence().to_dict())
        self.assertIn("ywta_runtime_challenge", hello.envelope.extra)

    def test_reconnect_and_close_connect_advertise_presence_once(self) -> None:
        """同一Clientのclose/connectでもPresenceは各接続のHelloに一度だけ載る。"""

        first_client, first_broker = socket.socketpair()
        second_client, second_broker = socket.socketpair()
        self.addCleanup(first_broker.close)
        self.addCleanup(second_broker.close)
        client = LinkClient(
            "127.0.0.1:24567",
            "blender:peer-001",
            presence=_presence(),
        )
        self.addCleanup(client.close)

        with patch(
            "ywta_link.client._open_loopback_socket",
            side_effect=[first_client, second_client],
        ):
            client.connect()
            first_hello = Frame.read_from(first_broker)
            client.join("room-a")
            Frame.read_from(first_broker)
            client.close()
            client.connect()
            second_hello = Frame.read_from(second_broker)
            replayed_join = Frame.read_from(second_broker)

        for hello in (first_hello, second_hello):
            self.assertEqual(hello.envelope.schema, PEER_HELLO_SCHEMA)
            self.assertEqual(hello.envelope.body, _presence().to_dict())
            self.assertEqual(hello.envelope.sender, hello.envelope.body["peer_id"])
        self.assertEqual(replayed_join.envelope.type, "join")

    def test_constructor_rejects_presence_sender_mismatch(self) -> None:
        """Presence peer_idとEnvelope senderの不一致を接続前に拒否する。"""

        mismatch = PeerPresence(
            peer_id="maya:peer-001",
            application="Maya",
            application_version="2024",
            plugin_version="0.1.0",
            protocol_versions=(1,),
            capabilities=("camera.read.v1",),
        )
        with self.assertRaises(LinkClientError):
            LinkClient("127.0.0.1:24567", "blender:peer-001", presence=mismatch)


if __name__ == "__main__":
    unittest.main()
