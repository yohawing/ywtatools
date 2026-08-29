"""YWTA Link v1 Authority handoffをClientへ接続するtransport。"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Mapping
from typing import Any

from .authority import (
    AUTHORITY_ACCEPTED_SCHEMA,
    AUTHORITY_REJECTED_SCHEMA,
    AUTHORITY_REQUEST_SCHEMA,
    AUTHORITY_SNAPSHOT_REQUEST_SCHEMA,
    AUTHORITY_SNAPSHOT_SCHEMA,
    AuthorityHandoffAccepted,
    AuthorityHandoffRejected,
    AuthorityHandoffRequest,
    AuthorityHandoffTracker,
    AuthoritySnapshot,
    AuthoritySnapshotRequest,
    AuthorityValidationError,
)
from .frame import Frame
from ._topic_lease import claim_topic, release_topic


class AuthorityTransportError(RuntimeError):
    """Authority transportの設定、lifecycle、wire検証、Client失敗を表す。"""


class AuthorityTransportThreadError(AuthorityTransportError):
    """owner thread以外からAuthority transportを操作したことを表す。"""


class AuthorityHandoffTransport:
    """一つのRoomのAuthority control topicを購読する薄いtransport。

    ClientとTrackerは借用し、接続、Room参加、Broker lifecycleは所有しない。
    Requestを受信しても自動でacceptまたはrejectせず、呼び出し側の明示判断を待つ。
    """

    def __init__(self, client: object, room: str, tracker: AuthorityHandoffTracker) -> None:
        """既存ClientとAuthority trackerを検証し、owner threadを記録する。"""

        for method_name in ("subscribe", "unsubscribe", "request", "response", "publish"):
            if not callable(getattr(client, method_name, None)):
                raise AuthorityTransportError(f"client must provide callable {method_name}()")
        if not isinstance(getattr(client, "peer_id", None), str) or not client.peer_id:
            raise AuthorityTransportError("client.peer_id must be a non-empty string")
        if type(tracker) is not AuthorityHandoffTracker:
            raise AuthorityTransportError("tracker must be exactly an AuthorityHandoffTracker")

        self._client = client
        self._peer_id = _identifier(client.peer_id, "peer_id")
        self._room = _identifier(room, "room")
        self._tracker = tracker
        self._session_id = _identifier(tracker.session_id, "session_id")
        self._topic = f"sync/{self._session_id}/control"
        self._owner_thread_id = threading.get_ident()
        self._active = False
        self._closed = False
        self._failed = False
        claim_topic(client, self._room, self._topic, self, AuthorityTransportError)

    @property
    def client(self) -> object:
        """送受信に使用する借用Clientを返す。"""

        return self._client

    @property
    def room(self) -> str:
        """購読対象のRoom IDを返す。"""

        return self._room

    @property
    def session_id(self) -> str:
        """紐付いたSession IDを返す。"""

        return self._session_id

    @property
    def topic(self) -> str:
        """Session control topicを返す。"""

        return self._topic

    @property
    def tracker(self) -> AuthorityHandoffTracker:
        """Authority stateを保持する借用Trackerを返す。"""

        return self._tracker

    @property
    def active(self) -> bool:
        """購読成功後で、closeされていないかを返す。"""

        return self._active

    @property
    def closed(self) -> bool:
        """close成功済みかを返す。"""

        return self._closed

    @property
    def failed(self) -> bool:
        """I/O失敗後にterminal failedへ遷移したかを返す。"""

        return self._failed

    def subscribe(self) -> bool:
        """Session control topicを一度だけ購読する。"""

        self._require_owner()
        self._require_open()
        self._require_healthy()
        if self._active:
            return False
        self._call_client("subscribe", self._client.subscribe, self._room, self._topic)
        self._active = True
        return True

    def request_handoff(self, request: AuthorityHandoffRequest) -> str:
        """次AuthorityとしてRequestを送信し、送信前にlocal pendingを登録する。"""

        self._require_owner()
        self._require_open()
        self._require_healthy()
        self._require_active()
        if type(request) is not AuthorityHandoffRequest:
            raise AuthorityTransportError("request must be exactly an AuthorityHandoffRequest")
        if request.session_id != self._session_id:
            raise AuthorityTransportError("request session_id does not match transport session")
        if request.next_authority != self._peer_id:
            raise AuthorityTransportError("request next_authority must match client.peer_id")

        request_message_id = uuid.uuid4().hex
        try:
            self._tracker.request_handoff(request, self._peer_id, request_message_id)
        except AuthorityTransportError:
            raise
        except Exception as exc:
            raise AuthorityTransportError(f"tracker.request_handoff() failed: {_error_text(exc)}") from exc

        try:
            result = self._call_client(
                "request",
                self._client.request,
                self._room,
                request.current_authority,
                message_id=request_message_id,
                schema=AUTHORITY_REQUEST_SCHEMA,
                body=request.to_dict(),
            )
            _require_message_id(result, "client.request()")
            if result != request_message_id:
                raise AuthorityTransportError("client.request() returned a different message ID")
        except AuthorityTransportError as exc:
            self._latch_failure(exc)
            raise
        return request_message_id

    def handle_frame(self, frame: Frame) -> bool:
        """Authority control frameを検証・適用し、処理対象ならTrueを返す。

        Requestの受信ではTrackerへpendingを登録するだけで、accept/rejectは行わない。
        Accepted responseはtransport完了の検証だけを行い、stateは変更しない。
        """

        self._require_owner()
        self._require_open()
        self._require_healthy()
        self._require_active()
        if type(frame) is not Frame:
            raise AuthorityTransportError("frame must be exactly a Frame")
        envelope = frame.envelope
        if envelope.room != self._room:
            return False

        if envelope.type == "publish":
            if envelope.topic != self._topic:
                return False
            if envelope.schema != AUTHORITY_ACCEPTED_SCHEMA:
                raise AuthorityTransportError("Authority control publish schema must be accepted")
            return self._handle_accepted_publish(frame)

        if envelope.type not in {"request", "response"}:
            return False
        if envelope.schema not in {
            AUTHORITY_REQUEST_SCHEMA,
            AUTHORITY_ACCEPTED_SCHEMA,
            AUTHORITY_REJECTED_SCHEMA,
            AUTHORITY_SNAPSHOT_REQUEST_SCHEMA,
            AUTHORITY_SNAPSHOT_SCHEMA,
        }:
            return False
        if envelope.topic is not None:
            raise AuthorityTransportError("Authority target message must not contain a topic")
        if not isinstance(frame.body, bytes) or frame.body:
            raise AuthorityTransportError("Authority frame must not contain a raw binary body")

        if envelope.type == "request":
            if envelope.schema == AUTHORITY_SNAPSHOT_REQUEST_SCHEMA:
                return self._handle_snapshot_request(frame)
            if envelope.schema != AUTHORITY_REQUEST_SCHEMA:
                raise AuthorityTransportError("Authority request schema mismatch")
            return self._handle_request(frame)
        if envelope.schema in {AUTHORITY_REQUEST_SCHEMA, AUTHORITY_SNAPSHOT_REQUEST_SCHEMA}:
            raise AuthorityTransportError("Authority response schema mismatch")
        if envelope.schema == AUTHORITY_SNAPSHOT_SCHEMA:
            return self._handle_snapshot_response(frame)
        return self._handle_response(frame)

    def accept_handoff(self, request: AuthorityHandoffRequest) -> tuple[str, str]:
        """現在Authorityとして明示的にRequestをacceptする。

        戻り値は`(target response message_id, Accepted publish message_id)`。
        Tracker stateはaccept時に更新され、送信順序はresponse、publishで固定する。
        """

        self._require_owner()
        self._require_open()
        self._require_healthy()
        self._require_active()
        if type(request) is not AuthorityHandoffRequest:
            raise AuthorityTransportError("request must be exactly an AuthorityHandoffRequest")
        pending = self._pending_request(request)
        try:
            accepted = self._tracker.accept_handoff(
                request,
                actor=self._peer_id,
                correlation_id=pending.request_message_id,
            )
        except AuthorityTransportError:
            raise
        except Exception as exc:
            raise AuthorityTransportError(f"tracker.accept_handoff() failed: {_error_text(exc)}") from exc

        try:
            response_id = self._send_response(
                request.next_authority,
                pending.request_message_id,
                AUTHORITY_ACCEPTED_SCHEMA,
                accepted.to_dict(),
            )
            publish_id = self._call_client(
                "publish",
                self._client.publish,
                self._room,
                topic=self._topic,
                correlation_id=pending.request_message_id,
                schema=AUTHORITY_ACCEPTED_SCHEMA,
                body=accepted.to_dict(),
            )
            _require_message_id(publish_id, "client.publish()")
        except AuthorityTransportError as exc:
            self._latch_failure(exc)
            raise
        return response_id, publish_id

    def reject_handoff(self, request: AuthorityHandoffRequest, reason: str) -> str:
        """現在Authorityとして明示的にRequestをrejectする。"""

        self._require_owner()
        self._require_open()
        self._require_healthy()
        self._require_active()
        if type(request) is not AuthorityHandoffRequest:
            raise AuthorityTransportError("request must be exactly an AuthorityHandoffRequest")
        pending = self._pending_request(request)
        try:
            rejected = self._tracker.reject_handoff(
                request,
                actor=self._peer_id,
                reason=reason,
                correlation_id=pending.request_message_id,
            )
        except AuthorityTransportError:
            raise
        except Exception as exc:
            raise AuthorityTransportError(f"tracker.reject_handoff() failed: {_error_text(exc)}") from exc
        try:
            return self._send_response(
                request.next_authority,
                pending.request_message_id,
                AUTHORITY_REJECTED_SCHEMA,
                rejected.to_dict(),
            )
        except AuthorityTransportError as exc:
            self._latch_failure(exc)
            raise

    def close(self) -> bool:
        """購読を解除して閉じる。Client自体はcloseしない。"""

        self._require_owner()
        if self._closed:
            return False
        if self._active:
            self._call_client("unsubscribe", self._client.unsubscribe, self._room, self._topic)
            self._active = False
        self._closed = True
        release_topic(self._client, self._room, self._topic, self)
        return True

    def _handle_request(self, frame: Frame) -> bool:
        """現在Authority向けのRequestをpendingへ登録する。"""

        envelope = frame.envelope
        request = self._decode_payload(frame, AuthorityHandoffRequest, "request")
        if envelope.target != self._peer_id:
            raise AuthorityTransportError("Authority request target must match client.peer_id")
        if envelope.sender != request.next_authority:
            raise AuthorityTransportError("Authority request sender must match next_authority")
        if request.current_authority != self._peer_id:
            raise AuthorityTransportError("Authority request current_authority must match target")
        try:
            self._tracker.request_handoff(request, envelope.sender, envelope.message_id)
        except AuthorityTransportError:
            raise
        except Exception as exc:
            raise AuthorityTransportError(f"tracker.request_handoff() failed: {_error_text(exc)}") from exc
        return True

    def _handle_snapshot_request(self, frame: Frame) -> bool:
        """現在のChannel authorityを照会元へtarget responseで返す。"""

        envelope = frame.envelope
        request = self._decode_payload(frame, AuthoritySnapshotRequest, "snapshot request")
        if envelope.target != self._peer_id:
            raise AuthorityTransportError("Authority snapshot request target must match client.peer_id")
        if envelope.sender == self._peer_id:
            raise AuthorityTransportError("Authority snapshot request sender must differ from client.peer_id")
        if envelope.correlation_id is not None:
            raise AuthorityTransportError("Authority snapshot request must not contain correlation_id")
        if request.session_id != self._session_id:
            raise AuthorityTransportError("Authority snapshot request session_id does not match transport session")
        try:
            state = self._tracker.state_for(request.channel_id)
        except Exception as exc:
            raise AuthorityTransportError(f"tracker.state_for() failed: {_error_text(exc)}") from exc
        snapshot = AuthoritySnapshot(
            session_id=self._session_id,
            channel_id=request.channel_id,
            authority=state.authority,
            authority_revision=state.revision,
        )
        try:
            self._send_response(
                envelope.sender,
                envelope.message_id,
                AUTHORITY_SNAPSHOT_SCHEMA,
                snapshot.to_dict(),
            )
        except AuthorityTransportError as exc:
            self._latch_failure(exc)
            raise
        return True

    def _handle_snapshot_response(self, frame: Frame) -> bool:
        """Bootstrap所有外のsnapshot responseを検証して状態変更せず破棄する。"""

        envelope = frame.envelope
        snapshot = self._decode_payload(frame, AuthoritySnapshot, "snapshot response")
        if envelope.target != self._peer_id:
            raise AuthorityTransportError("Authority snapshot response target must match client.peer_id")
        if envelope.sender == self._peer_id:
            raise AuthorityTransportError("Authority snapshot response sender must differ from client.peer_id")
        if not envelope.correlation_id:
            raise AuthorityTransportError("Authority snapshot response requires correlation_id")
        if snapshot.session_id != self._session_id:
            raise AuthorityTransportError("Authority snapshot response session_id does not match transport session")
        try:
            self._tracker.state_for(snapshot.channel_id)
        except Exception as exc:
            raise AuthorityTransportError(f"tracker.state_for() failed: {_error_text(exc)}") from exc
        return True

    def _handle_response(self, frame: Frame) -> bool:
        """Requester向けtarget responseを検証し、Rejectedだけpendingを解放する。"""

        envelope = frame.envelope
        payload_type: type[AuthorityHandoffAccepted | AuthorityHandoffRejected]
        if envelope.schema == AUTHORITY_ACCEPTED_SCHEMA:
            payload_type = AuthorityHandoffAccepted
        else:
            payload_type = AuthorityHandoffRejected
        payload = self._decode_payload(frame, payload_type, "response")
        if envelope.target != self._peer_id:
            raise AuthorityTransportError("Authority response target must match client.peer_id")
        if envelope.sender != payload.current_authority:
            raise AuthorityTransportError("Authority response sender must match current_authority")
        if payload.session_id != self._session_id:
            raise AuthorityTransportError("Authority response session_id does not match transport session")
        pending = self._pending_request(payload)
        if envelope.correlation_id != pending.request_message_id:
            raise AuthorityTransportError("Authority response correlation does not match pending request")
        if payload.next_authority != self._peer_id:
            raise AuthorityTransportError("Authority response next_authority must match client.peer_id")
        if payload.current_authority != pending.request.current_authority:
            raise AuthorityTransportError("Authority response current_authority does not match pending request")
        if envelope.schema == AUTHORITY_REJECTED_SCHEMA:
            try:
                self._tracker.apply_rejected(payload, actor=envelope.sender, correlation_id=envelope.correlation_id)
            except AuthorityTransportError:
                raise
            except Exception as exc:
                raise AuthorityTransportError(f"tracker.apply_rejected() failed: {_error_text(exc)}") from exc
        return True

    def _handle_accepted_publish(self, frame: Frame) -> bool:
        """control topicのAccepted fan-outだけをTrackerへ適用する。"""

        envelope = frame.envelope
        if envelope.target is not None:
            raise AuthorityTransportError("Accepted publish must not contain a target")
        if not envelope.correlation_id:
            raise AuthorityTransportError("Accepted publish requires correlation_id")
        accepted = self._decode_payload(frame, AuthorityHandoffAccepted, "accepted publish")
        if accepted.session_id != self._session_id:
            raise AuthorityTransportError("Accepted publish session_id does not match transport session")
        if envelope.sender != accepted.current_authority:
            raise AuthorityTransportError("Accepted publish sender must match current_authority")
        try:
            self._tracker.apply_accepted(
                accepted,
                actor=envelope.sender,
                correlation_id=envelope.correlation_id,
            )
        except AuthorityTransportError:
            raise
        except Exception as exc:
            raise AuthorityTransportError(f"tracker.apply_accepted() failed: {_error_text(exc)}") from exc
        return True

    def _pending_request(self, payload: AuthorityHandoffRequest | AuthorityHandoffAccepted | AuthorityHandoffRejected) -> Any:
        """payloadと同じidentityを持つlocal pendingを返す。"""

        try:
            pending = self._tracker.pending_for(payload.channel_id)
        except Exception as exc:
            raise AuthorityTransportError(f"tracker.pending_for() failed: {_error_text(exc)}") from exc
        if pending is None or pending.request != _request_identity(payload):
            raise AuthorityTransportError("Authority payload does not match a pending request")
        return pending

    @staticmethod
    def _decode_payload(frame: Frame, payload_type: type[Any], label: str) -> Any:
        """JSON object bodyを厳密なAuthority payloadへ変換する。"""

        if not isinstance(frame.body, bytes) or frame.body:
            raise AuthorityTransportError("Authority frame must not contain a raw binary body")
        if not isinstance(frame.envelope.body, Mapping):
            raise AuthorityTransportError(f"Authority {label} body must be a JSON object")
        try:
            return payload_type.from_dict(frame.envelope.body)
        except (AuthorityValidationError, TypeError, ValueError) as exc:
            raise AuthorityTransportError(f"invalid Authority {label} body: {_error_text(exc)}") from exc

    def _send_response(self, target: str, correlation_id: str, schema: str, body: Mapping[str, Any]) -> str:
        """target responseを送信し、Client結果を検証する。"""

        result = self._call_client(
            "response",
            self._client.response,
            self._room,
            target,
            correlation_id,
            schema=schema,
            body=dict(body),
        )
        return _require_message_id(result, "client.response()")

    def _require_owner(self) -> None:
        """生成元thread以外からの操作を拒否する。"""

        if threading.get_ident() != self._owner_thread_id:
            raise AuthorityTransportThreadError("AuthorityHandoffTransport operation must run on its owner thread")

    def _require_open(self) -> None:
        """close後の操作を拒否する。"""

        if self._closed:
            raise AuthorityTransportError("AuthorityHandoffTransport is closed")

    def _require_active(self) -> None:
        """購読成功前の操作を拒否する。"""

        if not self._active:
            raise AuthorityTransportError("AuthorityHandoffTransport is not subscribed")

    def _require_healthy(self) -> None:
        """terminal failed後の再利用を拒否する。"""

        if self._failed:
            raise AuthorityTransportError("AuthorityHandoffTransport has failed")

    def _latch_failure(self, error: AuthorityTransportError) -> None:
        """partial mutation後のI/O失敗をterminal failedへ固定する。"""

        del error
        self._failed = True

    @staticmethod
    def _call_client(operation: str, method: Any, *args: Any, **kwargs: Any) -> Any:
        """Client例外をtransport境界で型付けして再送出する。"""

        try:
            return method(*args, **kwargs)
        except AuthorityTransportError:
            raise
        except Exception as exc:
            raise AuthorityTransportError(f"client.{operation}() failed: {_error_text(exc)}") from exc


def _request_identity(
    payload: AuthorityHandoffRequest | AuthorityHandoffAccepted | AuthorityHandoffRejected,
) -> AuthorityHandoffRequest:
    """Accepted/RejectedからTracker照合用のRequest identityを作る。"""

    return AuthorityHandoffRequest(
        session_id=payload.session_id,
        channel_id=payload.channel_id,
        current_authority=payload.current_authority,
        next_authority=payload.next_authority,
        expected_authority_revision=payload.expected_authority_revision,
        change_id=payload.change_id,
    )


def _identifier(value: object, field_name: str) -> str:
    """空白だけでないUTF-8識別子を受け入れる。"""

    if not isinstance(value, str) or not value or not value.strip():
        raise AuthorityTransportError(f"{field_name} must be a non-whitespace string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise AuthorityTransportError(f"{field_name} must be valid UTF-8") from exc
    return value


def _require_message_id(value: object, operation: str) -> str:
    """Client操作の戻り値がnon-empty message IDであることを検証する。"""

    if not isinstance(value, str) or not value:
        raise AuthorityTransportError(f"{operation} must return a non-empty string message ID")
    return value


def _error_text(error: Exception) -> str:
    """ClientまたはTracker例外を安全な短い文字列へ変換する。"""

    try:
        message = str(error)
    except Exception:
        message = "<unprintable exception>"
    return message[:1024]


__all__ = ("AuthorityHandoffTransport", "AuthorityTransportError", "AuthorityTransportThreadError")
