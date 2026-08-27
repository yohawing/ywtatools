"""YWTA Link同期Clientの小さなProtocol検証。"""

from __future__ import annotations

import socket
import threading
import unittest
from unittest.mock import patch

from ywta_link.client import LinkClient, LinkClientError
from ywta_link.envelope import Envelope
from ywta_link.frame import Frame


class LinkClientTest(unittest.TestCase):
    """hello固定とendpoint検証を扱う。"""

    def test_connect_sends_hello_before_other_messages(self) -> None:
        """接続直後の最初のframeはClient自身のhelloになる。"""

        client_socket, broker_socket = socket.socketpair()
        self.addCleanup(broker_socket.close)
        client = LinkClient("127.0.0.1:24567", "blender:peer-001")
        self.addCleanup(client.close)

        with patch("ywta_link.client._open_loopback_socket", return_value=client_socket):
            client.connect()

        hello = Frame.read_from(broker_socket)
        self.assertEqual(hello.envelope.type, "hello")
        self.assertEqual(hello.envelope.sender, "blender:peer-001")
        client.join("shot-010")
        join = Frame.read_from(broker_socket)
        self.assertEqual(join.envelope.type, "join")
        self.assertEqual(join.envelope.sender, "blender:peer-001")
        self.assertEqual(join.envelope.room, "shot-010")

    def test_target_messages_require_room_before_socket_access(self) -> None:
        """Request、Response、ErrorはRoomなしに作れない。"""

        client = LinkClient(("127.0.0.1", 24567), "blender:peer-001")

        with self.assertRaises(LinkClientError):
            client.request("", "maya:peer-001")
        with self.assertRaises(LinkClientError):
            client.response("", "maya:peer-001", "request-001")
        with self.assertRaises(LinkClientError):
            client.error("", "maya:peer-001", "request-001")

    def test_runtime_connect_requires_matching_hello_acknowledgement(self) -> None:
        """manifest用接続はnonceとBroker instance tokenの両方を照合する。"""

        client_socket, broker_socket = socket.socketpair()
        self.addCleanup(broker_socket.close)
        client = LinkClient("127.0.0.1:24567", "blender:peer-001")
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
        self.assertEqual(received[0].envelope.type, "hello")
        self.assertIn("ywta_runtime_challenge", received[0].envelope.extra)

    def test_runtime_connect_rejects_wrong_instance_token(self) -> None:
        """TCPが開いても異なるinstance tokenなら接続済みにしない。"""

        client_socket, broker_socket = socket.socketpair()
        self.addCleanup(broker_socket.close)
        client = LinkClient("127.0.0.1:24567", "blender:peer-001")

        def respond() -> None:
            hello = Frame.read_from(broker_socket)
            Frame(
                Envelope(
                    protocol_version=1,
                    message_id="broker-ack-001",
                    type="hello",
                    sender="ywta-link:broker",
                    correlation_id=hello.envelope.message_id,
                    extra={
                        "ywta_runtime_challenge": hello.envelope.extra["ywta_runtime_challenge"],
                        "ywta_runtime_token": "replacement-token",
                    },
                ),
                b"",
            ).write_to(broker_socket)

        responder = threading.Thread(target=respond)
        responder.start()
        with patch("ywta_link.client._open_loopback_socket", return_value=client_socket):
            with self.assertRaises(LinkClientError):
                client.connect(timeout=1, expected_runtime_token="runtime-token-001")
        responder.join(timeout=1)

        self.assertFalse(responder.is_alive())
        self.assertIsNone(client._socket)

    def test_non_loopback_or_non_numeric_endpoint_is_rejected(self) -> None:
        """DNSとloopback外endpointを接続前に拒否する。"""

        for endpoint in (
            ("192.168.1.10", 24567),
            "localhost:24567",
            "example.test:24567",
            "127.0.0.1:0",
        ):
            with self.assertRaises(LinkClientError):
                LinkClient(endpoint, "blender:peer-001")


if __name__ == "__main__":
    unittest.main()
