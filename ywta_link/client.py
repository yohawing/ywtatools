"""YWTA Link v1 Brokerへ接続する小さな同期Client。"""

from __future__ import annotations

import ipaddress
import math
import socket
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .envelope import Envelope
from .frame import DEFAULT_FRAME_LIMITS, Frame, FrameError, FrameLimits, FrameTimeout
from .presence import PEER_HELLO_SCHEMA, PeerPresence

_RUNTIME_CHALLENGE_FIELD = "ywta_runtime_challenge"
_RUNTIME_TOKEN_FIELD = "ywta_runtime_token"
_RUNTIME_BROKER_SENDER = "ywta-link:broker"


class LinkClientError(ValueError):
    """Client設定または接続状態の不正。"""


@dataclass(frozen=True)
class _RuntimeBootstrap:
    """同じClient instanceで再利用するruntime bootstrap設定。"""

    runtime_file: str | None
    executable: str | None
    install_root: str | None
    idle_timeout: int
    startup_timeout: float
    stale_after: float


class LinkClient:
    """明示されたloopback endpointだけへ接続する同期Client。"""

    def __init__(
        self,
        endpoint: str | tuple[str, int],
        peer_id: str,
        *,
        presence: PeerPresence | None = None,
        frame_limits: FrameLimits = DEFAULT_FRAME_LIMITS,
    ) -> None:
        """endpointとPeer IDを検証し、未接続Clientを作る。"""

        self.endpoint = _parse_endpoint(endpoint)
        if not isinstance(peer_id, str) or not peer_id:
            raise LinkClientError("peer_id must be a non-empty string")
        if presence is not None and not isinstance(presence, PeerPresence):
            raise LinkClientError("presence must be a PeerPresence")
        if presence is not None and presence.peer_id != peer_id:
            raise LinkClientError("presence.peer_id must match peer_id")
        self.peer_id = peer_id
        self.presence = presence
        self.frame_limits = frame_limits
        self._socket: socket.socket | None = None
        self._joined_rooms: set[str] = set()
        self._subscriptions: set[tuple[str, str]] = set()
        self._runtime_bootstrap: _RuntimeBootstrap | None = None

    def __enter__(self) -> "LinkClient":
        """接続し、helloを送信してからClientを返す。"""

        return self.connect()

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        """context終了時に接続を閉じる。"""

        self.close()

    def connect(
        self,
        timeout: float | None = None,
        *,
        expected_runtime_token: str | None = None,
    ) -> "LinkClient":
        """TCP接続後、必要な場合だけruntime tokenのhello応答を検証する。"""

        if self._socket is not None:
            raise LinkClientError("client is already connected")
        if timeout is not None and not _is_positive_timeout(timeout):
            raise LinkClientError("timeout must be a positive number")
        if expected_runtime_token is not None and (not isinstance(expected_runtime_token, str) or not expected_runtime_token):
            raise LinkClientError("expected_runtime_token must be a non-empty string")
        if self.presence is not None:
            self.presence.validate()
        try:
            self._socket = _open_loopback_socket(self.endpoint, timeout)
            hello_schema = PEER_HELLO_SCHEMA if self.presence is not None else None
            hello_body = self.presence.to_dict() if self.presence is not None else None
            if expected_runtime_token is None:
                self._send("hello", schema=hello_schema, body=hello_body)
            else:
                challenge = _new_message_id()
                hello_id = self._send(
                    "hello",
                    schema=hello_schema,
                    body=hello_body,
                    extra={_RUNTIME_CHALLENGE_FIELD: challenge},
                )
                self._verify_runtime_ack(
                    hello_id,
                    challenge,
                    expected_runtime_token,
                    timeout,
                )
            self._reannounce_membership()
        except LinkClientError:
            self.close()
            raise
        except (OSError, FrameError) as exc:
            self.close()
            raise LinkClientError(f"could not connect to Broker: {exc}") from exc
        return self

    @classmethod
    def connect_or_start(
        cls,
        peer_id: str,
        *,
        presence: PeerPresence | None = None,
        endpoint: str | tuple[str, int] | None = None,
        runtime_file: str | None = None,
        executable: str | None = None,
        install_root: str | None = None,
        idle_timeout: int = 30,
        startup_timeout: float = 5.0,
        stale_after: float = 5.0,
    ) -> "LinkClient":
        """既存Brokerへ接続するか、runtime manifestを介して起動する。"""

        from .runtime import (
            RuntimeError,
            default_runtime_file,
            read_runtime_manifest,
            resolve_broker_executable,
            retire_stale_runtime,
            spawn_broker,
        )

        if not _is_positive_timeout(startup_timeout):
            raise LinkClientError("startup_timeout must be a positive number")
        if not _is_non_negative_timeout(stale_after):
            raise LinkClientError("stale_after must be a non-negative number")
        if isinstance(idle_timeout, bool) or not isinstance(idle_timeout, int) or idle_timeout <= 0:
            raise LinkClientError("idle_timeout must be a positive integer for bootstrap")
        if endpoint is None:
            endpoint = os_environ_endpoint()
        if endpoint is not None:
            return cls(endpoint, peer_id, presence=presence).connect(timeout=min(startup_timeout, 1.0))
        runtime_path = Path(runtime_file) if runtime_file is not None else default_runtime_file()
        if not runtime_path.is_absolute():
            raise LinkClientError("runtime_file must be an absolute path")
        deadline = time.monotonic() + startup_timeout
        candidate = None
        failed_connections = 0
        while time.monotonic() < deadline:
            if runtime_path.exists():
                try:
                    manifest = read_runtime_manifest(runtime_path)
                except RuntimeError:
                    if retire_stale_runtime(runtime_path, stale_after=stale_after):
                        candidate = None
                    time.sleep(0.05)
                    continue
                try:
                    client = cls(manifest.endpoint, peer_id, presence=presence).connect(
                        timeout=0.5,
                        expected_runtime_token=manifest.token,
                    )
                    client._runtime_bootstrap = _RuntimeBootstrap(
                        runtime_file=str(runtime_path),
                        executable=executable,
                        install_root=install_root,
                        idle_timeout=idle_timeout,
                        startup_timeout=startup_timeout,
                        stale_after=stale_after,
                    )
                    return client
                except LinkClientError:
                    failed_connections += 1
                    if failed_connections >= 2:
                        if retire_stale_runtime(
                            runtime_path,
                            manifest.token,
                            stale_after=stale_after,
                        ):
                            candidate = None
                            failed_connections = 0
            elif candidate is None or candidate.poll() is not None:
                try:
                    broker = resolve_broker_executable(
                        executable,
                        install_root=install_root,
                    )
                    candidate = spawn_broker(broker, runtime_path, idle_timeout=idle_timeout)
                except RuntimeError as exc:
                    raise LinkClientError(str(exc)) from exc
            time.sleep(0.05)
        raise LinkClientError("Broker did not become reachable before startup timeout")

    def close(self) -> None:
        """Clientが所有するsocketを閉じる。"""

        if self._socket is not None:
            try:
                self._socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self._socket.close()
            self._socket = None

    def reconnect(self, *, timeout: float | None = None) -> "LinkClient":
        """同一Peerと広告済みRoom/Topicを使い、同期的に接続し直す。"""

        if self._runtime_bootstrap is None and not _is_positive_timeout(timeout):
            raise LinkClientError("explicit endpoint reconnect requires a positive timeout")
        self.close()
        try:
            if self._runtime_bootstrap is None:
                self.connect(timeout)
            else:
                options = self._runtime_bootstrap
                replacement = type(self).connect_or_start(
                    self.peer_id,
                    presence=self.presence,
                    runtime_file=options.runtime_file,
                    executable=options.executable,
                    install_root=options.install_root,
                    idle_timeout=options.idle_timeout,
                    startup_timeout=options.startup_timeout,
                    stale_after=options.stale_after,
                )
                self.endpoint = replacement.endpoint
                self._socket = replacement._socket
                replacement._socket = None
                self._runtime_bootstrap = replacement._runtime_bootstrap
                self._reannounce_membership()
        except (LinkClientError, FrameError):
            self.close()
            raise
        return self

    def join(self, room: str) -> str:
        """Roomへ参加する。"""

        message_id = self._send("join", room=room)
        self._joined_rooms.add(room)
        return message_id

    def leave(self, room: str) -> str:
        """Roomから退出する。"""

        message_id = self._send("leave", room=room)
        self._joined_rooms.discard(room)
        self._subscriptions = {subscription for subscription in self._subscriptions if subscription[0] != room}
        return message_id

    def subscribe(self, room: str, topic: str) -> str:
        """Room内Topicを購読する。"""

        if room not in self._joined_rooms:
            raise LinkClientError("subscribe requires a locally joined room")
        message_id = self._send("subscribe", room=room, topic=topic)
        self._subscriptions.add((room, topic))
        return message_id

    def unsubscribe(self, room: str, topic: str) -> str:
        """Room内Topicの購読を解除する。"""

        message_id = self._send("unsubscribe", room=room, topic=topic)
        self._subscriptions.discard((room, topic))
        return message_id

    def publish(
        self,
        room: str,
        *,
        topic: str | None = None,
        correlation_id: str | None = None,
        schema: str | None = None,
        body: Any = None,
        raw_body: bytes = b"",
    ) -> str:
        """RoomまたはTopicへJSONとraw binary bodyをpublishする。

        `correlation_id`は、Authority handoffのようにTopicへfan-outする
        応答を元のpublishへ関連付ける場合に指定する。
        """

        return self._send(
            "publish",
            room=room,
            topic=topic,
            correlation_id=correlation_id,
            schema=schema,
            body=body,
            raw_body=raw_body,
        )

    def request(
        self,
        room: str,
        target: str,
        *,
        message_id: str | None = None,
        schema: str | None = None,
        body: Any = None,
        raw_body: bytes = b"",
    ) -> str:
        """同じRoom内のTargetへRequestを送る。

        `message_id`を指定すると、送信前にwire identityを予約できる。
        Authority handoffのように、送信前のlocal pending登録へ利用する。
        """

        return self._send(
            "request",
            room=room,
            target=target,
            message_id=message_id,
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

        if timeout is not None and not _is_positive_timeout(timeout):
            raise LinkClientError("timeout must be a positive number")
        client_socket = self._require_socket()
        previous_timeout = client_socket.gettimeout()
        if timeout is not None:
            client_socket.settimeout(timeout)
        try:
            return Frame.read_from(client_socket, self.frame_limits)
        except FrameError as exc:
            if isinstance(exc, FrameTimeout) and exc.connection_reusable:
                raise
            self.close()
            raise LinkClientError(f"Broker connection lost while receiving: {exc}") from exc
        except OSError as exc:
            self.close()
            raise LinkClientError(f"Broker connection lost while receiving: {exc}") from exc
        finally:
            if timeout is not None and self._socket is not None:
                client_socket.settimeout(previous_timeout)

    def _send(
        self,
        message_type: str,
        *,
        message_id: str | None = None,
        room: str | None = None,
        target: str | None = None,
        topic: str | None = None,
        correlation_id: str | None = None,
        schema: str | None = None,
        body: Any = None,
        raw_body: bytes = b"",
        extra: dict[str, Any] | None = None,
    ) -> str:
        """Client Peer IDに固定したEnvelopeを作り送信する。"""

        if message_type in {"request", "response", "error"} and not room:
            raise LinkClientError("target messages require a room")
        if message_id is None:
            message_id = _new_message_id()
        elif not isinstance(message_id, str) or not message_id:
            raise LinkClientError("message_id must be a non-empty string")
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
            extra={} if extra is None else extra,
        )
        try:
            Frame(envelope, raw_body).write_to(self._require_socket(), self.frame_limits)
        except FrameError as exc:
            if _is_send_disconnect(exc):
                self.close()
                raise LinkClientError(f"Broker connection lost while sending: {exc}") from exc
            raise
        return message_id

    def _reannounce_membership(self) -> None:
        """成功済み広告をRoom、Topicの辞書順で再送する。"""

        for room in sorted(self._joined_rooms):
            self._send("join", room=room)
        for room, topic in sorted(self._subscriptions):
            self._send("subscribe", room=room, topic=topic)

    def _verify_runtime_ack(
        self,
        hello_id: str,
        challenge: str,
        expected_token: str,
        timeout: float | None,
    ) -> None:
        """runtime manifestと同じinstance tokenを持つBroker応答だけを受理する。"""

        frame = self.receive(timeout)
        envelope = frame.envelope
        if (
            frame.body
            or envelope.type != "hello"
            or envelope.sender != _RUNTIME_BROKER_SENDER
            or envelope.correlation_id != hello_id
            or envelope.extra.get(_RUNTIME_CHALLENGE_FIELD) != challenge
            or envelope.extra.get(_RUNTIME_TOKEN_FIELD) != expected_token
        ):
            raise LinkClientError("Broker runtime token acknowledgement did not match manifest")

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


def os_environ_endpoint() -> str | None:
    """明示された環境変数endpointをPATH探索なしで返す。"""

    import os

    return os.environ.get("YWTA_LINK_ENDPOINT")


def _is_positive_timeout(value: float | None) -> bool:
    """明示endpoint再接続で必須の有限なtimeoutかを返す。"""

    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0 and math.isfinite(value)


def _is_non_negative_timeout(value: float) -> bool:
    """有限な0以上のtimeoutかを返す。"""

    return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 and math.isfinite(value)


def _is_send_disconnect(error: FrameError) -> bool:
    """送信時のtransport切断だけをsocket破棄対象にする。"""

    return str(error).startswith("frame write failed:") or str(error) == "frame write was truncated"


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
