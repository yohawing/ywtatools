"""YWTA Link v1 Authority handoffのwire型と状態追跡。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from .contract import SyncContract
from .errors import AuthorityViolation, StaleRevision, ValidationError
from .registry import DEFAULT_REGISTRY
from .session import ChannelRevisionTracker


AUTHORITY_REQUEST_SCHEMA = "ywta.sync.authority.request.v1"
AUTHORITY_ACCEPTED_SCHEMA = "ywta.sync.authority.accepted.v1"
AUTHORITY_REJECTED_SCHEMA = "ywta.sync.authority.rejected.v1"
AUTHORITY_SNAPSHOT_REQUEST_SCHEMA = "ywta.sync.authority.snapshot.request.v1"
AUTHORITY_SNAPSHOT_SCHEMA = "ywta.sync.authority.snapshot.v1"

AUTHORITY_REQUEST_FIELDS = frozenset(DEFAULT_REGISTRY.require_schema(AUTHORITY_REQUEST_SCHEMA))
AUTHORITY_ACCEPTED_FIELDS = frozenset(DEFAULT_REGISTRY.require_schema(AUTHORITY_ACCEPTED_SCHEMA))
AUTHORITY_REJECTED_FIELDS = frozenset(DEFAULT_REGISTRY.require_schema(AUTHORITY_REJECTED_SCHEMA))
AUTHORITY_SNAPSHOT_REQUEST_FIELDS = frozenset(DEFAULT_REGISTRY.require_schema(AUTHORITY_SNAPSHOT_REQUEST_SCHEMA))
AUTHORITY_SNAPSHOT_FIELDS = frozenset(DEFAULT_REGISTRY.require_schema(AUTHORITY_SNAPSHOT_SCHEMA))

_REQUEST_FIELDS_IN_ORDER = (
    "session_id",
    "channel_id",
    "current_authority",
    "next_authority",
    "expected_authority_revision",
    "change_id",
)
_ACCEPTED_FIELDS_IN_ORDER = (
    "session_id",
    "channel_id",
    "current_authority",
    "next_authority",
    "expected_authority_revision",
    "new_authority_revision",
    "change_id",
)
_REJECTED_FIELDS_IN_ORDER = (
    "session_id",
    "channel_id",
    "current_authority",
    "next_authority",
    "expected_authority_revision",
    "change_id",
    "reason",
)


class AuthorityValidationError(ValidationError):
    """Authority handoff payloadの検証失敗。"""


def _object(value: object, field_name: str) -> Mapping[str, Any]:
    """JSON objectとUTF-8へ変換できるkeyだけを受け入れる。"""

    if not isinstance(value, Mapping):
        raise AuthorityValidationError(f"{field_name} must be a JSON object")
    for key in value:
        if not isinstance(key, str):
            raise AuthorityValidationError(f"{field_name} object keys must be strings")
        try:
            key.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise AuthorityValidationError(f"{field_name} object keys must be valid UTF-8") from exc
    return value


def _identifier(value: object, field_name: str) -> str:
    """空白だけでないUTF-8文字列を識別子として受け入れる。"""

    if not isinstance(value, str) or not value or not value.strip():
        raise AuthorityValidationError(f"{field_name} must be a non-whitespace string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise AuthorityValidationError(f"{field_name} must be valid UTF-8") from exc
    return value


def _revision(value: object, field_name: str) -> int:
    """boolを除く0以上の整数をauthority revisionとして受け入れる。"""

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AuthorityValidationError(f"{field_name} must be a non-negative integer")
    return value


def _strict_fields(value: object, fields: frozenset[str], field_name: str) -> Mapping[str, Any]:
    """既知Fieldの過不足を検証したobjectを返す。"""

    data = _object(value, field_name)
    unknown = set(data) - fields
    missing = fields - set(data)
    if unknown or missing:
        raise AuthorityValidationError(f"{field_name} has unknown or missing fields: {sorted(unknown | missing)}")
    return data


def _decode(payload: str | bytes | bytearray, cls: type[Any], field_name: str) -> Any:
    """UTF-8 JSONをtyped payloadへ変換する。"""

    try:
        value = json.loads(payload)
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise AuthorityValidationError(f"invalid {field_name} JSON: {exc}") from exc
    return cls.from_dict(value)


class _AuthorityPayload:
    """Authority handoffの共通identity検証を提供する内部基底型。"""

    session_id: str
    channel_id: str
    current_authority: str
    next_authority: str
    expected_authority_revision: int
    change_id: str

    def _validate_identity(self) -> None:
        """handoff対象を識別する共通Fieldを検証する。"""

        for field_name in (
            "session_id",
            "channel_id",
            "current_authority",
            "next_authority",
            "change_id",
        ):
            value = _identifier(getattr(self, field_name), field_name)
            object.__setattr__(self, field_name, value)
        object.__setattr__(
            self,
            "expected_authority_revision",
            _revision(self.expected_authority_revision, "expected_authority_revision"),
        )
        if self.current_authority == self.next_authority:
            raise AuthorityValidationError("current_authority and next_authority must differ")

    def _identity_dict(self) -> dict[str, Any]:
        """共通identity部分をJSON-compatible dictへ変換する。"""

        return {
            "session_id": self.session_id,
            "channel_id": self.channel_id,
            "current_authority": self.current_authority,
            "next_authority": self.next_authority,
            "expected_authority_revision": self.expected_authority_revision,
            "change_id": self.change_id,
        }


@dataclass(frozen=True)
class AuthorityHandoffRequest(_AuthorityPayload):
    """Authority移譲を要求するtyped request payload。"""

    session_id: str
    channel_id: str
    current_authority: str
    next_authority: str
    expected_authority_revision: int
    change_id: str

    def __post_init__(self) -> None:
        """直接constructorでもrequestの不変条件を適用する。"""

        self._validate_identity()

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AuthorityHandoffRequest":
        """JSON objectを厳密なrequest型へ変換する。"""

        data = _strict_fields(value, AUTHORITY_REQUEST_FIELDS, "authority request")
        return cls(**{field_name: data[field_name] for field_name in _REQUEST_FIELDS_IN_ORDER})

    @classmethod
    def decode(cls, payload: str | bytes | bytearray) -> "AuthorityHandoffRequest":
        """UTF-8 JSONからrequestを復元する。"""

        return _decode(payload, cls, "authority request")

    def to_dict(self) -> dict[str, Any]:
        """requestを新しいJSON-compatible dictへ変換する。"""

        return self._identity_dict()

    def encode(self) -> str:
        """requestを決定的なcompact JSONへ変換する。"""

        try:
            return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False)
        except (TypeError, ValueError, UnicodeEncodeError) as exc:
            raise AuthorityValidationError(f"cannot encode authority request: {exc}") from exc


@dataclass(frozen=True)
class AuthorityHandoffAccepted(_AuthorityPayload):
    """Authority移譲を受理したtyped response payload。"""

    session_id: str
    channel_id: str
    current_authority: str
    next_authority: str
    expected_authority_revision: int
    new_authority_revision: int
    change_id: str

    def __post_init__(self) -> None:
        """直接constructorでもacceptedの不変条件を適用する。"""

        self._validate_identity()
        new_revision = _revision(self.new_authority_revision, "new_authority_revision")
        if new_revision != self.expected_authority_revision + 1:
            raise AuthorityValidationError("new_authority_revision must equal expected_authority_revision + 1")
        object.__setattr__(self, "new_authority_revision", new_revision)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AuthorityHandoffAccepted":
        """JSON objectを厳密なaccepted型へ変換する。"""

        data = _strict_fields(value, AUTHORITY_ACCEPTED_FIELDS, "authority accepted")
        return cls(**{field_name: data[field_name] for field_name in _ACCEPTED_FIELDS_IN_ORDER})

    @classmethod
    def decode(cls, payload: str | bytes | bytearray) -> "AuthorityHandoffAccepted":
        """UTF-8 JSONからacceptedを復元する。"""

        return _decode(payload, cls, "authority accepted")

    def to_dict(self) -> dict[str, Any]:
        """acceptedを新しいJSON-compatible dictへ変換する。"""

        result = self._identity_dict()
        result["new_authority_revision"] = self.new_authority_revision
        return result

    def encode(self) -> str:
        """acceptedを決定的なcompact JSONへ変換する。"""

        try:
            return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False)
        except (TypeError, ValueError, UnicodeEncodeError) as exc:
            raise AuthorityValidationError(f"cannot encode authority accepted: {exc}") from exc


@dataclass(frozen=True)
class AuthorityHandoffRejected(_AuthorityPayload):
    """Authority移譲を拒否したtyped response payload。"""

    session_id: str
    channel_id: str
    current_authority: str
    next_authority: str
    expected_authority_revision: int
    change_id: str
    reason: str

    def __post_init__(self) -> None:
        """直接constructorでもrejectedの不変条件を適用する。"""

        self._validate_identity()
        object.__setattr__(self, "reason", _identifier(self.reason, "reason"))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AuthorityHandoffRejected":
        """JSON objectを厳密なrejected型へ変換する。"""

        data = _strict_fields(value, AUTHORITY_REJECTED_FIELDS, "authority rejected")
        return cls(**{field_name: data[field_name] for field_name in _REJECTED_FIELDS_IN_ORDER})

    @classmethod
    def decode(cls, payload: str | bytes | bytearray) -> "AuthorityHandoffRejected":
        """UTF-8 JSONからrejectedを復元する。"""

        return _decode(payload, cls, "authority rejected")

    def to_dict(self) -> dict[str, Any]:
        """rejectedを新しいJSON-compatible dictへ変換する。"""

        result = self._identity_dict()
        result["reason"] = self.reason
        return result

    def encode(self) -> str:
        """rejectedを決定的なcompact JSONへ変換する。"""

        try:
            return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False)
        except (TypeError, ValueError, UnicodeEncodeError) as exc:
            raise AuthorityValidationError(f"cannot encode authority rejected: {exc}") from exc


@dataclass(frozen=True)
class AuthorityState:
    """Channel単位の現在Authorityと専用revision。"""

    authority: str
    revision: int

    def __post_init__(self) -> None:
        """Authority stateの不変条件を検証する。"""

        object.__setattr__(self, "authority", _identifier(self.authority, "authority"))
        object.__setattr__(self, "revision", _revision(self.revision, "authority_revision"))


@dataclass(frozen=True)
class AuthoritySnapshotRequest:
    """Authority state照会のtarget request payload。"""

    session_id: str
    channel_id: str

    def __post_init__(self) -> None:
        """直接constructorでも照会対象の識別子を検証する。"""

        object.__setattr__(self, "session_id", _identifier(self.session_id, "session_id"))
        object.__setattr__(self, "channel_id", _identifier(self.channel_id, "channel_id"))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AuthoritySnapshotRequest":
        """JSON objectを厳密なsnapshot requestへ変換する。"""

        data = _strict_fields(value, AUTHORITY_SNAPSHOT_REQUEST_FIELDS, "authority snapshot request")
        return cls(session_id=data["session_id"], channel_id=data["channel_id"])

    def to_dict(self) -> dict[str, str]:
        """snapshot requestを新しいJSON-compatible dictへ変換する。"""

        return {"session_id": self.session_id, "channel_id": self.channel_id}


@dataclass(frozen=True)
class AuthoritySnapshot:
    """Session参加時に照合するChannel authorityの読み取り専用snapshot。"""

    session_id: str
    channel_id: str
    authority: str
    authority_revision: int

    def __post_init__(self) -> None:
        """直接constructorでもsnapshotの不変条件を検証する。"""

        object.__setattr__(self, "session_id", _identifier(self.session_id, "session_id"))
        object.__setattr__(self, "channel_id", _identifier(self.channel_id, "channel_id"))
        object.__setattr__(self, "authority", _identifier(self.authority, "authority"))
        object.__setattr__(
            self,
            "authority_revision",
            _revision(self.authority_revision, "authority_revision"),
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AuthoritySnapshot":
        """JSON objectを厳密なauthority snapshotへ変換する。"""

        data = _strict_fields(value, AUTHORITY_SNAPSHOT_FIELDS, "authority snapshot")
        return cls(
            session_id=data["session_id"],
            channel_id=data["channel_id"],
            authority=data["authority"],
            authority_revision=data["authority_revision"],
        )

    def to_dict(self) -> dict[str, Any]:
        """snapshotを新しいJSON-compatible dictへ変換する。"""

        return {
            "session_id": self.session_id,
            "channel_id": self.channel_id,
            "authority": self.authority,
            "authority_revision": self.authority_revision,
        }


@dataclass(frozen=True)
class PendingHandoff:
    """Channelへ登録したhandoff requestと元Envelopeのmessage ID。"""

    request: AuthorityHandoffRequest
    request_message_id: str

    def __post_init__(self) -> None:
        """pending identityとrequest message IDを検証する。"""

        if not isinstance(self.request, AuthorityHandoffRequest):
            raise AuthorityValidationError("pending request must be an AuthorityHandoffRequest")
        object.__setattr__(self, "request_message_id", _identifier(self.request_message_id, "request_message_id"))


class AuthorityHandoffTracker:
    """ChannelごとのAuthority handoffを追跡する副作用のない状態管理器。

    Trackerのrevisionはcontent revisionとは別のcontrol-plane revisionであり、各Channelを0から開始する。
    acceptはauthorityとrevisionの確認後にauthority、revision、pendingを同一操作で更新する。
    """

    def __init__(
        self,
        contract: SyncContract | Mapping[str, str],
        session_id: str | None = None,
        *,
        initial_authority_revisions: Mapping[str, int] | None = None,
    ) -> None:
        """Sync ContractまたはChannel/Authority対応からtrackerを作成する。

        snapshotから再開する場合は、Channelごとのauthority revisionを
        ``initial_authority_revisions`` に渡す。
        """

        if isinstance(contract, SyncContract):
            self.session_id = contract.session_id
        else:
            if not isinstance(contract, Mapping):
                raise AuthorityValidationError("contract must be a SyncContract or channel authority mapping")
            if session_id is None:
                raise AuthorityValidationError("session_id is required for a channel authority mapping")
            self.session_id = _identifier(session_id, "session_id")
        self._content_tracker = ChannelRevisionTracker(
            contract,
            initial_authority_revisions=initial_authority_revisions,
        )
        self._lock = self._content_tracker.lock
        self._pending: dict[str, PendingHandoff] = {}

    @classmethod
    def from_snapshot(
        cls,
        snapshot: AuthoritySnapshot,
    ) -> "AuthorityHandoffTracker":
        """単一ChannelのAuthority snapshotを初期状態としてtrackerを作る。"""

        if not isinstance(snapshot, AuthoritySnapshot):
            raise AuthorityValidationError("snapshot must be an AuthoritySnapshot")
        return cls(
            {snapshot.channel_id: snapshot.authority},
            snapshot.session_id,
            initial_authority_revisions={snapshot.channel_id: snapshot.authority_revision},
        )

    def state_for(self, channel_id: str) -> AuthorityState:
        """Channelの現在Authorityとauthority revisionを返す。"""

        with self._lock:
            return AuthorityState(
                self._content_tracker.authority_for(channel_id),
                self._content_tracker.authority_revision_for(channel_id),
            )

    def pending_for(self, channel_id: str) -> PendingHandoff | None:
        """Channelのpending requestを返す。"""

        with self._lock:
            self._content_tracker.authority_for(channel_id)
            return self._pending.get(channel_id)

    def request_handoff(self, request: AuthorityHandoffRequest, requester: str, request_message_id: str) -> None:
        """新しいhandoff requestを登録し、staleまたは同時要求を拒否する。

        Requestは次Authority本人から送信され、元Envelopeのmessage IDを必ず伴う。
        """

        if not isinstance(request, AuthorityHandoffRequest):
            raise AuthorityValidationError("request must be an AuthorityHandoffRequest")
        requester = _identifier(requester, "requester")
        request_message_id = _identifier(request_message_id, "request_message_id")
        with self._lock:
            self._validate_session(request.session_id)
            state = self.state_for(request.channel_id)
            if request.expected_authority_revision != state.revision:
                raise StaleRevision(
                    f"authority revision {request.expected_authority_revision} is not current revision {state.revision}"
                )
            if request.current_authority != state.authority:
                raise AuthorityViolation(f"request current authority is not current for channel: {request.channel_id!r}")
            if requester != request.next_authority:
                raise AuthorityViolation("requester must be the next authority")
            if request.channel_id in self._pending:
                raise StaleRevision(f"handoff already pending for channel: {request.channel_id!r}")
            self._pending[request.channel_id] = PendingHandoff(request, request_message_id)

    def accept_handoff(
        self,
        request: AuthorityHandoffRequest,
        actor: str,
        correlation_id: str,
    ) -> AuthorityHandoffAccepted:
        """現在Authorityだけがrequestを受理し、stateをatomicに更新する。"""

        if not isinstance(request, AuthorityHandoffRequest):
            raise AuthorityValidationError("request must be an AuthorityHandoffRequest")
        actor = _identifier(actor, "actor")
        correlation_id = _identifier(correlation_id, "correlation_id")
        with self._lock:
            pending = self._validate_pending(request)
            self._validate_correlation(correlation_id, pending)
            state = self.state_for(request.channel_id)
            if actor != state.authority:
                raise AuthorityViolation(f"actor is not authority for channel: {request.channel_id!r}")
            new_revision = state.revision + 1
            accepted = AuthorityHandoffAccepted(
                session_id=request.session_id,
                channel_id=request.channel_id,
                current_authority=state.authority,
                next_authority=request.next_authority,
                expected_authority_revision=state.revision,
                new_authority_revision=new_revision,
                change_id=request.change_id,
            )
            transferred_revision = self._content_tracker.transfer_authority(
                request.channel_id,
                state.authority,
                request.next_authority,
                state.revision,
            )
            if transferred_revision != accepted.new_authority_revision:
                raise StaleRevision("authority transfer revision changed during handoff")
            del self._pending[request.channel_id]
            return accepted

    def reject_handoff(
        self,
        request: AuthorityHandoffRequest,
        actor: str,
        reason: str,
        correlation_id: str,
    ) -> AuthorityHandoffRejected:
        """現在Authorityだけがrequestを拒否し、stateを変更せずpendingを解放する。"""

        if not isinstance(request, AuthorityHandoffRequest):
            raise AuthorityValidationError("request must be an AuthorityHandoffRequest")
        actor = _identifier(actor, "actor")
        correlation_id = _identifier(correlation_id, "correlation_id")
        with self._lock:
            pending = self._validate_pending(request)
            self._validate_correlation(correlation_id, pending)
            state = self.state_for(request.channel_id)
            if actor != state.authority:
                raise AuthorityViolation(f"actor is not authority for channel: {request.channel_id!r}")
            rejected = AuthorityHandoffRejected(
                session_id=request.session_id,
                channel_id=request.channel_id,
                current_authority=state.authority,
                next_authority=request.next_authority,
                expected_authority_revision=state.revision,
                change_id=request.change_id,
                reason=reason,
            )
            del self._pending[request.channel_id]
            return rejected

    def apply_accepted(self, accepted: AuthorityHandoffAccepted, actor: str, correlation_id: str) -> None:
        """Accepted fan-outをobserverまたはlocal pendingへ適用する。

        現Authorityが選んだAcceptedをorderingの正本とし、同一requestのpendingならcorrelationを照合する。
        別requestのpendingはwinnerに置き換えて解放する。
        """

        if not isinstance(accepted, AuthorityHandoffAccepted):
            raise AuthorityValidationError("accepted must be an AuthorityHandoffAccepted")
        actor = _identifier(actor, "actor")
        correlation_id = _identifier(correlation_id, "correlation_id")
        with self._lock:
            state = self.state_for(accepted.channel_id)
            if actor != state.authority or accepted.current_authority != state.authority:
                raise AuthorityViolation(f"actor is not authority for channel: {accepted.channel_id!r}")
            if accepted.expected_authority_revision != state.revision:
                raise StaleRevision(
                    f"authority revision {accepted.expected_authority_revision} is not current revision {state.revision}"
                )
            if accepted.new_authority_revision != state.revision + 1:
                raise StaleRevision("accepted authority revision is not the next revision")
            pending = self._pending.get(accepted.channel_id)
            if pending is not None and self._pending_matches_payload(pending, accepted):
                self._validate_correlation(correlation_id, pending)
            transferred_revision = self._content_tracker.transfer_authority(
                accepted.channel_id,
                state.authority,
                accepted.next_authority,
                state.revision,
            )
            if transferred_revision != accepted.new_authority_revision:
                raise StaleRevision("authority transfer revision changed during response application")
            if pending is not None:
                del self._pending[accepted.channel_id]

    def apply_rejected(self, rejected: AuthorityHandoffRejected, actor: str, correlation_id: str) -> None:
        """Rejected fan-outを一致するlocal pendingだけへ適用する。"""

        if not isinstance(rejected, AuthorityHandoffRejected):
            raise AuthorityValidationError("rejected must be an AuthorityHandoffRejected")
        actor = _identifier(actor, "actor")
        correlation_id = _identifier(correlation_id, "correlation_id")
        with self._lock:
            state = self.state_for(rejected.channel_id)
            if actor != state.authority or rejected.current_authority != state.authority:
                raise AuthorityViolation(f"actor is not authority for channel: {rejected.channel_id!r}")
            if rejected.expected_authority_revision != state.revision:
                raise StaleRevision(
                    f"authority revision {rejected.expected_authority_revision} is not current revision {state.revision}"
                )
            pending = self._pending.get(rejected.channel_id)
            if pending is None or not self._pending_matches_payload(pending, rejected):
                return
            self._validate_correlation(correlation_id, pending)
            del self._pending[rejected.channel_id]

    def accept_content(self, channel_id: str, sender: str, revision: int) -> int:
        """現在Authorityからのcontent revisionを受理するfacade。"""

        with self._lock:
            return self._content_tracker.accept_content(channel_id, sender, revision)

    def revision_for(self, channel_id: str) -> int | None:
        """最後に受理したcontent revisionを返すfacade。"""

        with self._lock:
            return self._content_tracker.revision_for(channel_id)

    def observe_disconnect(self, peer_id: str) -> tuple[str, ...]:
        """Peer切断を観測するが、Channel authorityを自動昇格しない。"""

        _identifier(peer_id, "peer_id")
        with self._lock:
            return tuple(
                sorted(
                    channel_id
                    for channel_id in self._content_tracker.channels()
                    if self._content_tracker.authority_for(channel_id) == peer_id
                )
            )

    def _validate_session(self, session_id: str) -> None:
        """Trackerに紐付いたSession IDとrequestの一致を検証する。"""

        if self.session_id is not None and session_id != self.session_id:
            raise AuthorityValidationError("request session_id does not match tracker session")

    def _validate_pending(self, request: AuthorityHandoffRequest) -> PendingHandoff:
        """pending requestが同一identityであることを検証する。"""

        self._validate_session(request.session_id)
        self.state_for(request.channel_id)
        pending = self._pending.get(request.channel_id)
        if pending is None or pending.request != request:
            raise StaleRevision(f"request is not pending for channel: {request.channel_id!r}")
        return pending

    @staticmethod
    def _pending_matches_payload(pending: PendingHandoff, payload: _AuthorityPayload) -> bool:
        """Accepted/Rejected payloadがpending requestと同じidentityかを返す。"""

        return all(
            getattr(pending.request, field_name) == getattr(payload, field_name) for field_name in _REQUEST_FIELDS_IN_ORDER
        )

    @staticmethod
    def _validate_correlation(correlation_id: str, pending: PendingHandoff) -> None:
        """accepted/rejectedのEnvelope correlationと元Request IDを照合する。"""

        if correlation_id != pending.request_message_id:
            raise StaleRevision("correlation_id does not match request message_id")


__all__ = (
    "AUTHORITY_ACCEPTED_FIELDS",
    "AUTHORITY_ACCEPTED_SCHEMA",
    "AUTHORITY_REJECTED_FIELDS",
    "AUTHORITY_REJECTED_SCHEMA",
    "AUTHORITY_REQUEST_FIELDS",
    "AUTHORITY_REQUEST_SCHEMA",
    "AUTHORITY_SNAPSHOT_REQUEST_SCHEMA",
    "AUTHORITY_SNAPSHOT_REQUEST_FIELDS",
    "AUTHORITY_SNAPSHOT_SCHEMA",
    "AUTHORITY_SNAPSHOT_FIELDS",
    "AuthorityHandoffAccepted",
    "AuthorityHandoffRejected",
    "AuthorityHandoffRequest",
    "AuthorityHandoffTracker",
    "AuthoritySnapshot",
    "AuthoritySnapshotRequest",
    "AuthorityState",
    "AuthorityValidationError",
    "PendingHandoff",
)
