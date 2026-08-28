"""YWTA Link同期Clientの小さなProtocol検証。"""

from __future__ import annotations

import socket
import threading
import unittest
from unittest.mock import patch

from ywta_link.client import LinkClient, LinkClientError, _RuntimeBootstrap
from ywta_link.envelope import Envelope
from ywta_link.frame import DEFAULT_FRAME_LIMITS, FIXED_HEADER_LENGTH, Frame, FrameError, FrameLimits


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

    def test_publish_can_correlate_topic_fanout_response(self) -> None:
        """Topicへのpublish応答へ元Message IDを関連付けられる。"""

        client_socket, broker_socket = socket.socketpair()
        self.addCleanup(broker_socket.close)
        client = LinkClient("127.0.0.1:24567", "blender:peer-001")
        self.addCleanup(client.close)

        with patch("ywta_link.client._open_loopback_socket", return_value=client_socket):
            client.connect()
        Frame.read_from(broker_socket)

        client.publish(
            "shot-010",
            topic="sync/session-001/control",
            correlation_id="request-001",
            schema="ywta.sync.authority.accepted.v1",
            body={"accepted": True},
        )
        published = Frame.read_from(broker_socket)

        self.assertEqual(published.envelope.type, "publish")
        self.assertEqual(published.envelope.topic, "sync/session-001/control")
        self.assertEqual(published.envelope.correlation_id, "request-001")

    def test_authority_request_targets_current_authority(self) -> None:
        """Authority Requestをtarget=current_authorityのEnvelopeとして送信する。"""

        client_socket, broker_socket = socket.socketpair()
        self.addCleanup(broker_socket.close)
        client = LinkClient("127.0.0.1:24567", "maya:peer-001")
        self.addCleanup(client.close)

        with patch("ywta_link.client._open_loopback_socket", return_value=client_socket):
            client.connect()
        Frame.read_from(broker_socket)

        client.request(
            "shot-010",
            "blender:peer-001",
            schema="ywta.sync.authority.request.v1",
            body={"channel_id": "timeline"},
        )
        request = Frame.read_from(broker_socket)

        self.assertEqual(request.envelope.type, "request")
        self.assertEqual(request.envelope.target, "blender:peer-001")
        self.assertIsNone(request.envelope.correlation_id)

    def test_target_messages_require_room_before_socket_access(self) -> None:
        """Request、Response、ErrorはRoomなしに作れない。"""

        client = LinkClient(("127.0.0.1", 24567), "blender:peer-001")

        with self.assertRaises(LinkClientError):
            client.subscribe("room-a", "topic-a")
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

    def test_reconnect_reuses_instance_and_reannounces_remaining_state_in_order(self) -> None:
        """同じClientがRoom、Topicを辞書順で再広告し、解除済み状態を送らない。"""

        first_client, first_broker = socket.socketpair()
        second_client, second_broker = socket.socketpair()
        self.addCleanup(first_broker.close)
        self.addCleanup(second_broker.close)
        client = LinkClient("127.0.0.1:24567", "blender:peer-001")
        self.addCleanup(client.close)

        with patch(
            "ywta_link.client._open_loopback_socket",
            side_effect=[first_client, second_client],
        ):
            client.connect()
            Frame.read_from(first_broker)
            client.join("room-b")
            client.join("room-a")
            client.subscribe("room-a", "topic-z")
            client.subscribe("room-a", "topic-a")
            client.subscribe("room-b", "topic-gone")
            client.leave("room-b")
            client.unsubscribe("room-a", "topic-z")
            client.reconnect(timeout=1)

        replayed = [Frame.read_from(second_broker) for _ in range(3)]
        self.assertEqual(replayed[0].envelope.sender, client.peer_id)
        self.assertEqual(
            [(frame.envelope.type, frame.envelope.room, frame.envelope.topic) for frame in replayed],
            [
                ("hello", None, None),
                ("join", "room-a", None),
                ("subscribe", "room-a", "topic-a"),
            ],
        )
        self.assertEqual(client.peer_id, "blender:peer-001")

    def test_reconnect_failure_closes_new_socket_and_keeps_state_for_retry(self) -> None:
        """再広告が失敗しても古いsocketは復活せず、次回用の状態は残る。"""

        class FailingSocket:
            """hello後の再広告だけを失敗させるsocket代替。"""

            def __init__(self) -> None:
                self._writes = 0

            def sendall(self, _data: bytes) -> None:
                if self._writes:
                    raise BrokenPipeError("test disconnect")
                self._writes += 1

            @staticmethod
            def shutdown(_how: int) -> None:
                pass

            @staticmethod
            def close() -> None:
                pass

        initial_client, initial_broker = socket.socketpair()
        self.addCleanup(initial_broker.close)
        client = LinkClient("127.0.0.1:24567", "blender:peer-001")
        self.addCleanup(client.close)
        with patch("ywta_link.client._open_loopback_socket", return_value=initial_client):
            client.connect()
        Frame.read_from(initial_broker)
        client.join("room-a")

        with patch("ywta_link.client._open_loopback_socket", return_value=FailingSocket()):
            with self.assertRaises(LinkClientError):
                client.reconnect(timeout=1)

        self.assertIsNone(client._socket)
        self.assertEqual(client._joined_rooms, {"room-a"})

    def test_explicit_reconnect_requires_finite_timeout_before_closing_socket(self) -> None:
        """明示endpointのreconnectは無期限待機を許可しない。"""

        client_socket, broker_socket = socket.socketpair()
        self.addCleanup(client_socket.close)
        self.addCleanup(broker_socket.close)
        client = LinkClient("127.0.0.1:24567", "blender:peer-001")
        client._socket = client_socket

        for timeout in (None, 0, float("inf")):
            with self.assertRaises(LinkClientError):
                client.reconnect(timeout=timeout)
            self.assertIs(client._socket, client_socket)

    def test_connect_and_receive_reject_non_finite_timeout_before_socket_io(self) -> None:
        """無限値とNaNをsocket APIへ渡す前に拒否する。"""

        client = LinkClient("127.0.0.1:24567", "blender:peer-001")
        for timeout in (float("inf"), float("nan")):
            with self.assertRaises(LinkClientError):
                client.connect(timeout=timeout)
            with self.assertRaises(LinkClientError):
                client.receive(timeout=timeout)

    def test_close_then_connect_reannounces_state_once(self) -> None:
        """通常connect再利用でも成功済みRoom/Topicを一度だけ再広告する。"""

        first_client, first_broker = socket.socketpair()
        second_client, second_broker = socket.socketpair()
        self.addCleanup(first_broker.close)
        self.addCleanup(second_broker.close)
        client = LinkClient("127.0.0.1:24567", "blender:peer-001")
        self.addCleanup(client.close)

        with patch(
            "ywta_link.client._open_loopback_socket",
            side_effect=[first_client, second_client],
        ):
            client.connect()
            Frame.read_from(first_broker)
            client.join("room-a")
            client.subscribe("room-a", "topic-a")
            client.close()
            client.connect()

        replayed = [Frame.read_from(second_broker) for _ in range(3)]
        self.assertEqual(
            [(frame.envelope.type, frame.envelope.room, frame.envelope.topic) for frame in replayed],
            [
                ("hello", None, None),
                ("join", "room-a", None),
                ("subscribe", "room-a", "topic-a"),
            ],
        )

    def test_runtime_replay_nontransport_frame_error_closes_socket_and_keeps_state(self) -> None:
        """replayのframe limit失敗でもreplacement socketを閉じ、広告状態を残す。"""

        class AcceptingSocket:
            """sendallを受理し、close呼出を記録するsocket代替。"""

            def __init__(self) -> None:
                self.closed = False

            @staticmethod
            def sendall(_data: bytes) -> None:
                pass

            @staticmethod
            def shutdown(_how: int) -> None:
                pass

            def close(self) -> None:
                self.closed = True

        peer_id = "blender:peer-001"
        header_length = (
            len(
                Frame(
                    Envelope(
                        protocol_version=1,
                        message_id="x" * 32,
                        type="join",
                        sender=peer_id,
                        room="room-a",
                    )
                ).to_bytes()
            )
            - FIXED_HEADER_LENGTH
        )
        client = LinkClient("127.0.0.1:24567", peer_id)
        client.frame_limits = FrameLimits(
            max_header_length=header_length,
            max_body_length=DEFAULT_FRAME_LIMITS.max_body_length,
        )
        client._joined_rooms.add("room-a")
        client._subscriptions.add(("room-a", "topic-a"))
        options = _RuntimeBootstrap(None, None, None, 1, 1.0, 0.0)
        client._runtime_bootstrap = options
        replacement = LinkClient("127.0.0.1:24567", peer_id)
        replacement._socket = AcceptingSocket()
        replacement._runtime_bootstrap = options

        with patch.object(LinkClient, "connect_or_start", return_value=replacement):
            with self.assertRaises(FrameError):
                client.reconnect()

        self.assertIsNone(client._socket)
        self.assertTrue(replacement._socket is None)
        self.assertTrue(client._joined_rooms)
        self.assertTrue(client._subscriptions)

    def test_transport_disconnects_are_normalized_but_receive_timeout_keeps_socket(self) -> None:
        """send/EOFはLinkClientErrorへ正規化し、read timeoutは接続を維持する。"""

        client_socket, broker_socket = socket.socketpair()
        self.addCleanup(broker_socket.close)
        client = LinkClient("127.0.0.1:24567", "blender:peer-001")
        self.addCleanup(client.close)
        client._socket = client_socket

        with self.assertRaises(FrameError):
            client.receive(timeout=0.01)
        self.assertIs(client._socket, client_socket)
        broker_socket.close()
        with self.assertRaises(LinkClientError):
            client.receive(timeout=0.1)
        self.assertIsNone(client._socket)

        partial_client, partial_broker = socket.socketpair()
        self.addCleanup(partial_broker.close)
        client._socket = partial_client
        partial_broker.sendall(b"Y")
        with self.assertRaises(LinkClientError):
            client.receive(timeout=0.01)
        self.assertIsNone(client._socket)

        class BrokenSocket:
            """即時BrokenPipeを返す最小socket代替。"""

            @staticmethod
            def sendall(_data: bytes) -> None:
                raise BrokenPipeError("test disconnect")

            @staticmethod
            def shutdown(_how: int) -> None:
                pass

            @staticmethod
            def close() -> None:
                pass

        client._socket = BrokenSocket()
        with self.assertRaises(LinkClientError):
            client.join("room-a")
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
