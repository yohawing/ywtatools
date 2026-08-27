"""YWTA Link同期Clientの小さなProtocol検証。"""

from __future__ import annotations

import socket
import unittest
from unittest.mock import patch

from ywta_link.client import LinkClient, LinkClientError
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
