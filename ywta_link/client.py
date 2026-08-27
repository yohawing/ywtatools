"""YWTA Link v1 Brokerへ接続する小さな同期Client。"""

from __future__ import annotations

import ipaddress
import socket
import uuid
from typing import Any

from .envelope import Envelope
from .frame import DEFAULT_FRAME_LIMITS, Frame, FrameError, FrameLimits


class LinkClientError(ValueError):
    """Client設定または接続状態の不正。"""


class LinkClient:
    """明示されたloopback endpointだけへ接続する同期Client。"""

    def __init__(
        self,
        endpoint: str | tuple[str, int],
        peer_id: str,
        *,
        frame_limits: FrameLimits = DEFAULT_FRAME_LIMITS,
    ) -> None:
        """endpointとPeer IDを検証し、未接続Clientを作る。"""

        self.endpoint = _parse_endpoint(endpoint)
        if not isinstance(peer_id, str) or not peer_id:
            raise LinkClientError("peer_id must be a non-empty string")
        self.peer_id = peer_id
        self.frame_limits = frame_limits
        self._socket: socket.socket | None = None

    def __enter__(self) -> "LinkClient":
        """接続し、helloを送信してからClientを返す。"""

        return self.connect()

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        """context終了時に接続を閉じる。"""

        self.close()

    def connect(self, timeout: float | None = None) -> "LinkClient":
        """TCP接続後、必ず最初にhelloを送信する。"""

        if self._socket is not None:
            raise LinkClientError("client is already connected")
        try:
            self._socket = _open_loopback_socket(self.endpoint, timeout)
            self._send("hello")
        except (OSError, FrameError) as exc:
            self.close()
            raise LinkClientError(f"could not connect to Broker: {exc}") from exc
        return self

    def close(self) -> None:
        """Clientが所有するsocketを閉じる。"""

        if self._socket is not None:
            try:
                self._socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self._socket.close()
            self._socket = None

    def join(self, room: str) -> str:
        """Roomへ参加する。"""

        return self._send("join", room=room)

    def leave(self, room: str) -> str:
        """Roomから退出する。"""

        return self._send("leave", room=room)

    def subscribe(self, room: str, topic: str) -> str:
        """Room内Topicを購読する。"""

        return self._send("subscribe", room=room, topic=topic)

    def unsubscribe(self, room: str, topic: str) -> str:
        """Room内Topicの購読を解除する。"""

        return self._send("unsubscribe", room=room, topic=topic)

    def publish(
        self,
        room: str,
        *,
        topic: str | None = None,
        schema: str | None = None,
        body: Any = None,
        raw_body: bytes = b"",
    ) -> str:
        """RoomまたはTopicへJSONとraw binary bodyをpublishする。"""

        return self._send(
            "publish",
            room=room,
            topic=topic,
            schema=schema,
            body=body,
            raw_body=raw_body,
        )

    def request(
        self,
        room: str,
        target: str,
        *,
        schema: str | None = None,
        body: Any = None,
        raw_body: bytes = b"",
    ) -> str:
        """同じRoom内のTargetへRequestを送る。"""

        return self._send(
            "request",
            room=room,
            target=target,
            schema=schema,
            body=body,
            raw_body=raw_body,
        )

    def response(
        self,
        room: str,
        target: str,
        correlation_id: str,
        *,
        schema: str | None = None,
        body: Any = None,
        raw_body: bytes = b"",
    ) -> str:
        """同じRoom内のRequestへResponseを返す。"""

        return self._send(
            "response",
            room=room,
            target=target,
            correlation_id=correlation_id,
            schema=schema,
            body=body,
            raw_body=raw_body,
        )

    def error(
        self,
        room: str,
        target: str,
        correlation_id: str,
        *,
        schema: str | None = None,
        body: Any = None,
        raw_body: bytes = b"",
    ) -> str:
        """同じRoom内のRequestへErrorを返す。"""

        return self._send(
            "error",
            room=room,
            target=target,
            correlation_id=correlation_id,
            schema=schema,
            body=body,
            raw_body=raw_body,
        )

    def receive(self, timeout: float | None = None) -> Frame:
        """次のframeを同期的に待ち、必要なら一時timeoutを適用する。"""

        client_socket = self._require_socket()
        previous_timeout = client_socket.gettimeout()
        if timeout is not None:
            client_socket.settimeout(timeout)
        try:
            return Frame.read_from(client_socket, self.frame_limits)
        finally:
            if timeout is not None:
                client_socket.settimeout(previous_timeout)

    def _send(
        self,
        message_type: str,
        *,
        room: str | None = None,
        target: str | None = None,
        topic: str | None = None,
        correlation_id: str | None = None,
        schema: str | None = None,
        body: Any = None,
        raw_body: bytes = b"",
    ) -> str:
        """Client Peer IDに固定したEnvelopeを作り送信する。"""

        if message_type in {"request", "response", "error"} and not room:
            raise LinkClientError("target messages require a room")
        message_id = _new_message_id()
        envelope = Envelope(
            protocol_version=1,
            message_id=message_id,
            type=message_type,
            sender=self.peer_id,
            room=room,
            target=target,
            topic=topic,
            correlation_id=correlation_id,
            schema=schema,
            body=body,
        )
        Frame(envelope, raw_body).write_to(self._require_socket(), self.frame_limits)
        return message_id

    def _require_socket(self) -> socket.socket:
        """接続済みsocketを返し、未接続なら拒否する。"""

        if self._socket is None:
            raise LinkClientError("client is not connected")
        return self._socket


def _parse_endpoint(endpoint: str | tuple[str, int]) -> tuple[str, int]:
    """DNSを使わないnumeric loopback endpointだけを受け入れる。"""

    if isinstance(endpoint, tuple) and len(endpoint) == 2:
        host, port = endpoint
    elif isinstance(endpoint, str):
        host, port = _split_endpoint(endpoint)
    else:
        raise LinkClientError("endpoint must be a numeric host and port")
    if not isinstance(host, str) or isinstance(port, bool) or not isinstance(port, int):
        raise LinkClientError("endpoint must be a numeric host and port")
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise LinkClientError("endpoint host must be a numeric IP address") from exc
    if not address.is_loopback:
        raise LinkClientError("endpoint host must be loopback")
    if not 1 <= port <= 65535:
        raise LinkClientError("endpoint port must be between 1 and 65535")
    return host, port


def _split_endpoint(value: str) -> tuple[str, int]:
    """IPv4または角括弧付きIPv6の`host:port`を分解する。"""

    if value.startswith("["):
        host, separator, port_text = value[1:].partition("]:")
        if not separator:
            raise LinkClientError("endpoint must use [ipv6]:port")
    else:
        host, separator, port_text = value.rpartition(":")
        if not separator or ":" in host:
            raise LinkClientError("endpoint must use numeric host:port")
    try:
        port = int(port_text)
    except ValueError as exc:
        raise LinkClientError("endpoint port must be an integer") from exc
    return host, port


def _new_message_id() -> str:
    """Protocolで要求される一意なMessage IDを生成する。"""

    return uuid.uuid4().hex


def _open_loopback_socket(endpoint: tuple[str, int], timeout: float | None) -> socket.socket:
    """numeric IP familyへ直接connectし、名前解決を発生させない。"""

    host, port = endpoint
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    client_socket = socket.socket(family, socket.SOCK_STREAM)
    try:
        if timeout is not None:
            client_socket.settimeout(timeout)
        address: tuple[str, int] | tuple[str, int, int, int]
        address = (host, port, 0, 0) if family == socket.AF_INET6 else (host, port)
        client_socket.connect(address)
        if timeout is not None:
            client_socket.settimeout(None)
    except OSError:
        client_socket.close()
        raise
    return client_socket
