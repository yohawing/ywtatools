"""SessionをRoomのephemeral slotからbootstrapするprivate共通consumer。"""

from __future__ import annotations

import json
import math
import time
import uuid
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Callable, Mapping

from .authority import (
    AUTHORITY_ACCEPTED_SCHEMA,
    AUTHORITY_SNAPSHOT_REQUEST_SCHEMA,
    AUTHORITY_SNAPSHOT_SCHEMA,
    AuthorityHandoffAccepted,
    AuthorityHandoffTracker,
    AuthoritySnapshot,
    AuthoritySnapshotRequest,
    AuthorityValidationError,
)
from .client import LinkClient
from .errors import _bounded_error_message, _non_negative_finite, _positive_finite, _validate_identifier
from .frame import Frame, FrameTimeout
from .playback import PLAYBACK_SCHEMA
from .playback_session import (
    PlaybackSession,
    PlaybackSessionConfig,
    compose_playback_session,
)
from .presence import PeerPresence
from .registry import DEFAULT_REGISTRY, SLOT_DESCRIPTOR_SCHEMA, SLOT_JOIN_SCHEMA
from .time import RationalRate


BROKER_PEER_ID = "ywta-link:broker"
PLAYBACK_SLOT_METADATA_FIELDS = frozenset({"contract_version", "channel_id", "playback_schema", "wire_timebase"})
SLOT_DESCRIPTOR_FIELDS = DEFAULT_REGISTRY.require_schema(SLOT_DESCRIPTOR_SCHEMA)


class PlaybackBootstrapError(RuntimeError):
    """Common Session slotまたはAuthority snapshotのbootstrap失敗。"""


@dataclass(frozen=True)
class PlaybackBootstrapConfig:
    """DCC Adapterが渡すPlayback bootstrap設定。"""

    application_id: str
    application: str
    application_version: str
    plugin_version: str
    host_unit_rate: RationalRate | Mapping[str, Any]
    time_unit: str
    room: str = "default"
    slot_id: str = "playback-default.v1"
    channel_id: str = "playback"
    topic: str = "playback"
    wire_timebase: RationalRate = RationalRate(120000, 1)
    bootstrap_timeout: float = 1.0
    max_attempts: int = 3
    queue_capacity: int = 256
    stop_timeout: float = 1.0
    handoff_timeout: float = 1.0

    def __post_init__(self) -> None:
        """bootstrapに必要な識別子、timebase、有限設定を検証する。"""

        for name in (
            "application_id",
            "application",
            "application_version",
            "plugin_version",
            "time_unit",
            "room",
            "slot_id",
            "channel_id",
            "topic",
        ):
            _identifier(getattr(self, name), name)
        try:
            host_rate = (
                self.host_unit_rate
                if isinstance(self.host_unit_rate, RationalRate)
                else RationalRate.from_dict(self.host_unit_rate, field_name="host_unit_rate")
            )
        except (TypeError, ValueError) as error:
            raise PlaybackBootstrapError(f"invalid host_unit_rate: {error}") from error
        object.__setattr__(self, "host_unit_rate", host_rate)
        if not isinstance(self.wire_timebase, RationalRate):
            raise PlaybackBootstrapError("wire_timebase must be a RationalRate")
        if self.wire_timebase != RationalRate(120000, 1):
            raise PlaybackBootstrapError("wire_timebase must be RationalRate(120000, 1)")
        if not _positive_finite(self.bootstrap_timeout):
            raise PlaybackBootstrapError("bootstrap_timeout must be a positive finite number")
        if isinstance(self.max_attempts, bool) or not isinstance(self.max_attempts, int) or not 1 <= self.max_attempts <= 16:
            raise PlaybackBootstrapError("max_attempts must be an integer from 1 to 16")
        if isinstance(self.queue_capacity, bool) or not isinstance(self.queue_capacity, int) or self.queue_capacity <= 0:
            raise PlaybackBootstrapError("queue_capacity must be a positive integer")
        if not _non_negative_finite(self.stop_timeout):
            raise PlaybackBootstrapError("stop_timeout must be a non-negative finite number")
        if not _positive_finite(self.handoff_timeout):
            raise PlaybackBootstrapError("handoff_timeout must be a positive finite number")
        ticks = Fraction(self.wire_timebase.rate_num * host_rate.rate_den, host_rate.rate_num)
        if ticks.denominator != 1 or ticks.numerator <= 0:
            raise PlaybackBootstrapError("host_unit_rate must divide the canonical wire_timebase exactly")

    @property
    def ticks_per_host_unit(self) -> int:
        """Host時刻1単位を表すwire tick数を返す。"""

        ticks = Fraction(self.wire_timebase.rate_num * self.host_unit_rate.rate_den, self.host_unit_rate.rate_num)
        return ticks.numerator

    @property
    def slot_metadata(self) -> dict[str, Any]:
        """slot joinへ送るPlayback metadataを新しいdictで返す。"""

        return {
            "contract_version": 1,
            "channel_id": self.channel_id,
            "playback_schema": PLAYBACK_SCHEMA,
            "wire_timebase": self.wire_timebase.to_dict(),
        }

    def presence(self, peer_id: str) -> PeerPresence:
        """指定Peer向けの決定的なPresence広告を作る。"""

        return PeerPresence(
            peer_id=peer_id,
            application=self.application,
            application_version=self.application_version,
            plugin_version=self.plugin_version,
            protocol_versions=(1,),
            capabilities=("playback.apply.v1", "playback.read.v1", "sync.authority.v1"),
        )

    def validate_slot_metadata(self, value: object) -> None:
        """Broker descriptorのPlayback metadataを厳密に検証する。"""

        _validate_playback_metadata(value, self)

    def build_session_config(self, peer_id: str, session_id: str, authority: str) -> PlaybackSessionConfig:
        """reconcile済みidentityからPlayback Session設定を作る。"""

        return PlaybackSessionConfig(
            peer_id=peer_id,
            session_id=session_id,
            room=self.room,
            topic=self.topic,
            channel_id=self.channel_id,
            initial_authority=authority,
            ticks_per_host_unit=self.ticks_per_host_unit,
            host_unit_rate=self.host_unit_rate,
            time_unit=self.time_unit,
            queue_capacity=self.queue_capacity,
            stop_timeout=self.stop_timeout,
            handoff_timeout=self.handoff_timeout,
        )


ConnectionFactory = Callable[[str, PeerPresence], object]


def bootstrap_playback_session(
    config: PlaybackBootstrapConfig,
    host_factory: Callable[[object], object],
    lifecycle_factory: Callable[[object, object], object],
    connection_factory: ConnectionFactory | None = None,
) -> PlaybackSession:
    """slotをclaimし、必要ならsnapshotでreconcileして未開始Sessionを返す。"""

    return bootstrap_session(
        config,
        PlaybackBootstrapConfig,
        host_factory,
        lifecycle_factory,
        compose_playback_session,
        connection_factory,
        "Playback",
    )


def bootstrap_session(
    config: object,
    config_type: type[Any],
    host_factory: Callable[[object], object],
    lifecycle_factory: Callable[[object, object], object],
    compose_session: Callable[..., Any],
    connection_factory: ConnectionFactory | None,
    label: str,
) -> Any:
    """DCC非依存なslot、Authority reconcile、Session compositionを実行する。"""

    if not isinstance(config, config_type):
        raise PlaybackBootstrapError(f"config must be a {config_type.__name__}")
    if not callable(host_factory) or not callable(lifecycle_factory):
        raise PlaybackBootstrapError("host_factory and lifecycle_factory must be callable")
    factory = _default_connection_factory if connection_factory is None else connection_factory
    if not callable(factory):
        raise PlaybackBootstrapError("connection_factory must be callable")

    last_error: BaseException | None = None
    for attempt in range(config.max_attempts):
        peer_id = f"{config.application_id}:{uuid.uuid4().hex}"
        presence = config.presence(peer_id)
        client: object | None = None
        try:
            client = factory(peer_id, presence)
            _validate_client(client, peer_id)
            tracker, session_config = _bootstrap_attempt(client, config, peer_id)
        except Exception as error:
            last_error = error
            if client is not None:
                try:
                    client.close()
                except Exception as close_error:
                    raise PlaybackBootstrapError(
                        f"bootstrap failed and Client.close() failed: {_error_text(close_error)}"
                    ) from error
            if attempt + 1 >= config.max_attempts:
                break
            continue

        # Composition failure is a host/lifecycle boundary failure and is not retryable.
        return compose_session(
            session_config,
            host_factory,
            lifecycle_factory,
            lambda _config, connected_client=client: connected_client,  # type: ignore[arg-type]
            authority_tracker=tracker,
        )

    detail = _error_text(last_error) if last_error is not None else "unknown bootstrap failure"
    raise PlaybackBootstrapError(f"{label} bootstrap failed after {config.max_attempts} attempts: {detail}") from last_error


def _default_connection_factory(peer_id: str, presence: PeerPresence) -> LinkClient:
    """Presenceを広告してBrokerへ接続または起動する。"""

    return LinkClient.connect_or_start(peer_id, presence=presence)


def _bootstrap_attempt(
    client: object,
    config: Any,
    peer_id: str,
) -> tuple[AuthorityHandoffTracker, object]:
    """一つの専用Clientでslot joinからreconcileまでを完了する。"""

    deadline = _deadline(config.bootstrap_timeout)
    _message_id(client.join(config.room), "room join")
    request_id = client.request(
        config.room,
        BROKER_PEER_ID,
        schema=SLOT_JOIN_SCHEMA,
        body={"slot_id": config.slot_id, "metadata": config.slot_metadata},
    )
    request_id = _message_id(request_id, "slot join request")
    descriptor = _receive_descriptor(client, config, peer_id, request_id, deadline)

    if descriptor["created"]:
        tracker = AuthorityHandoffTracker.from_snapshot(
            AuthoritySnapshot(descriptor["session_id"], config.channel_id, peer_id, 0)
        )
        current_authority = peer_id
    else:
        tracker, current_authority = _reconcile_existing_slot(
            client,
            config,
            peer_id,
            descriptor,
            deadline,
        )

    session_config = config.build_session_config(peer_id, descriptor["session_id"], current_authority)
    return tracker, session_config


def _receive_descriptor(
    client: object,
    config: Any,
    peer_id: str,
    request_id: str,
    deadline: float,
) -> dict[str, Any]:
    """slot joinに対応する一つのdescriptor responseを厳密に受信する。"""

    frame = _receive(client, deadline)
    _require_clean_envelope(frame)
    envelope = frame.envelope
    if (
        envelope.type != "response"
        or envelope.sender != BROKER_PEER_ID
        or envelope.target != peer_id
        or envelope.room != config.room
        or envelope.correlation_id != request_id
        or envelope.schema != SLOT_DESCRIPTOR_SCHEMA
        or envelope.topic is not None
    ):
        raise PlaybackBootstrapError("slot descriptor response routing or schema mismatch")
    if frame.body:
        raise PlaybackBootstrapError("slot descriptor response must not contain a raw binary body")
    data = _strict_object(envelope.body, SLOT_DESCRIPTOR_FIELDS, "slot descriptor")
    for field_name in ("slot_id", "session_id", "initial_authority", "state_peer"):
        _identifier(data[field_name], field_name)
    _validate_metadata(data["metadata"], "slot descriptor metadata")
    config.validate_slot_metadata(data["metadata"])
    if type(data["created"]) is not bool:
        raise PlaybackBootstrapError("slot descriptor created must be a boolean")
    if data["slot_id"] != config.slot_id:
        raise PlaybackBootstrapError("slot descriptor slot_id does not match config")
    if data["created"]:
        if data["initial_authority"] != peer_id or data["state_peer"] != peer_id:
            raise PlaybackBootstrapError("created slot descriptor must identify the local Peer")
    elif data["state_peer"] == peer_id:
        raise PlaybackBootstrapError("existing slot descriptor state_peer must differ from local Peer")
    return dict(data)


def _reconcile_existing_slot(
    client: object,
    config: Any,
    peer_id: str,
    descriptor: Mapping[str, Any],
    deadline: float,
) -> tuple[AuthorityHandoffTracker, str]:
    """control topicを先に購読し、snapshotとbuffer済みAcceptedをreconcileする。"""

    session_id = descriptor["session_id"]
    state_peer = descriptor["state_peer"]
    control_topic = f"sync/{session_id}/control"
    _message_id(client.subscribe(config.room, control_topic), "Authority control subscription")
    snapshot_request = AuthoritySnapshotRequest(session_id=session_id, channel_id=config.channel_id)
    snapshot_request_id = _message_id(
        client.request(
            config.room,
            state_peer,
            schema=AUTHORITY_SNAPSHOT_REQUEST_SCHEMA,
            body=snapshot_request.to_dict(),
        ),
        "authority snapshot request",
    )

    buffered: list[tuple[AuthorityHandoffAccepted, str]] = []
    snapshot: AuthoritySnapshot | None = None
    while snapshot is None:
        frame = _receive(client, deadline)
        if _is_accepted_publish(frame, config.room, control_topic):
            if len(buffered) >= 256:
                raise PlaybackBootstrapError("Authority Accepted bootstrap buffer is full")
            accepted = _decode_accepted(frame)
            if accepted.session_id != session_id or accepted.channel_id != config.channel_id:
                raise PlaybackBootstrapError("buffered Accepted session or channel mismatch")
            if frame.envelope.sender != accepted.current_authority:
                raise PlaybackBootstrapError("buffered Accepted sender does not match current_authority")
            buffered.append((accepted, frame.envelope.correlation_id))
            continue
        snapshot = _decode_snapshot_response(frame, config, peer_id, state_peer, snapshot_request_id, session_id)

    tracker = AuthorityHandoffTracker.from_snapshot(snapshot)
    try:
        pending = _reconcile_buffered_prefix(buffered, snapshot)
        for accepted, correlation_id in pending:
            tracker.apply_accepted(
                accepted,
                actor=accepted.current_authority,
                correlation_id=correlation_id,
            )
    except PlaybackBootstrapError:
        raise
    except Exception as error:
        raise PlaybackBootstrapError(f"buffered Authority reconciliation failed: {_error_text(error)}") from error
    return tracker, tracker.state_for(config.channel_id).authority


def _reconcile_buffered_prefix(
    buffered: list[tuple[AuthorityHandoffAccepted, str]],
    snapshot: AuthoritySnapshot,
) -> list[tuple[AuthorityHandoffAccepted, str]]:
    """socket順のAccepted chainを検証し、snapshot後のsuffixだけ返す。"""

    if not buffered:
        return []

    chain: list[tuple[AuthorityHandoffAccepted, str]] = []
    for identity in buffered:
        accepted = identity[0]
        if chain:
            previous = chain[-1][0]
            if accepted.new_authority_revision == previous.new_authority_revision:
                if identity != chain[-1]:
                    raise PlaybackBootstrapError("Accepted at the same revision has conflicting identity")
                continue
            if (
                accepted.expected_authority_revision != previous.new_authority_revision
                or accepted.current_authority != previous.next_authority
            ):
                raise PlaybackBootstrapError("buffered Accepted chain has a revision or authority gap")
        chain.append(identity)

    first = chain[0][0]
    last = chain[-1][0]
    revision = snapshot.authority_revision
    if not first.expected_authority_revision <= revision <= last.new_authority_revision:
        raise PlaybackBootstrapError("snapshot revision is outside the buffered Accepted chain")

    if revision == first.expected_authority_revision:
        authority = first.current_authority
    else:
        authority = next(
            accepted.next_authority for accepted, _correlation_id in chain if accepted.new_authority_revision == revision
        )
    if authority != snapshot.authority:
        raise PlaybackBootstrapError("buffered Accepted chain conflicts with snapshot authority")

    return [identity for identity in chain if identity[0].new_authority_revision > revision]


def _decode_snapshot_response(
    frame: Frame,
    config: Any,
    peer_id: str,
    state_peer: str,
    request_id: str,
    session_id: str,
) -> AuthoritySnapshot:
    """snapshot responseのrouting、body、session、channelを厳密に検証する。"""

    _require_clean_envelope(frame)
    envelope = frame.envelope
    if (
        envelope.type != "response"
        or envelope.sender != state_peer
        or envelope.target != peer_id
        or envelope.room != config.room
        or envelope.correlation_id != request_id
        or envelope.schema != AUTHORITY_SNAPSHOT_SCHEMA
        or envelope.topic is not None
    ):
        raise PlaybackBootstrapError("Authority snapshot response routing or schema mismatch")
    if frame.body:
        raise PlaybackBootstrapError("Authority snapshot response must not contain a raw binary body")
    try:
        snapshot = AuthoritySnapshot.from_dict(envelope.body)
    except (AuthorityValidationError, TypeError, ValueError) as error:
        raise PlaybackBootstrapError(f"invalid Authority snapshot response: {_error_text(error)}") from error
    if snapshot.session_id != session_id or snapshot.channel_id != config.channel_id:
        raise PlaybackBootstrapError("Authority snapshot session or channel does not match slot")
    return snapshot


def _decode_accepted(frame: Frame) -> AuthorityHandoffAccepted:
    """Accepted publish bodyをtyped payloadへ変換する。"""

    _require_clean_envelope(frame)
    if frame.body:
        raise PlaybackBootstrapError("Authority Accepted publish must not contain a raw binary body")
    if not frame.envelope.correlation_id:
        raise PlaybackBootstrapError("Authority Accepted publish requires correlation_id")
    try:
        return AuthorityHandoffAccepted.from_dict(frame.envelope.body)
    except (AuthorityValidationError, TypeError, ValueError) as error:
        raise PlaybackBootstrapError(f"invalid Authority Accepted publish: {_error_text(error)}") from error


def _is_accepted_publish(frame: object, room: str, topic: str) -> bool:
    """frameがAccepted control publishの候補かを判定する。"""

    if type(frame) is not Frame:
        raise PlaybackBootstrapError("bootstrap receive must return a Frame")
    envelope = frame.envelope
    return (
        envelope.type == "publish"
        and envelope.room == room
        and envelope.topic == topic
        and envelope.schema == AUTHORITY_ACCEPTED_SCHEMA
        and envelope.target is None
    )


def _receive(client: object, deadline: float) -> Frame:
    """有限deadline内に次のFrameを一つだけ受信する。"""

    remaining = deadline - time.monotonic()
    if not math.isfinite(remaining) or remaining <= 0:
        raise PlaybackBootstrapError("Session bootstrap timed out")
    try:
        frame = client.receive(timeout=remaining)
    except (FrameTimeout, TimeoutError) as error:
        raise PlaybackBootstrapError("Session bootstrap timed out") from error
    except Exception as error:
        raise PlaybackBootstrapError(f"Session bootstrap receive failed: {_error_text(error)}") from error
    if type(frame) is not Frame:
        raise PlaybackBootstrapError("bootstrap receive must return a Frame")
    return frame


def _validate_client(client: object, peer_id: str) -> None:
    """専用Client identityとbootstrapに必要な操作を検証する。"""

    if getattr(client, "peer_id", None) != peer_id:
        raise PlaybackBootstrapError("Client peer_id does not match generated Peer ID")
    for method_name in ("join", "request", "subscribe", "receive", "close"):
        if not callable(getattr(client, method_name, None)):
            raise PlaybackBootstrapError(f"Client must provide {method_name}()")


def _require_clean_envelope(frame: Frame) -> None:
    """bootstrap対象Frameの未定義Envelope extraを拒否する。"""

    if type(frame) is not Frame:
        raise PlaybackBootstrapError("bootstrap receive must return a Frame")
    if frame.envelope.extra:
        raise PlaybackBootstrapError("bootstrap Frame envelope contains unexpected fields")


def _strict_object(value: object, fields: frozenset[str], field_name: str) -> Mapping[str, Any]:
    """JSON objectのField過不足を検証する。"""

    if not isinstance(value, Mapping):
        raise PlaybackBootstrapError(f"{field_name} must be a JSON object")
    if set(value) != set(fields) or any(not isinstance(key, str) for key in value):
        raise PlaybackBootstrapError(f"{field_name} has unknown or missing fields")
    return value


def _validate_metadata(value: object, field_name: str) -> None:
    """opaque metadataが小さなJSON objectであることを検証する。"""

    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise PlaybackBootstrapError(f"{field_name} must be a JSON object")
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False)
        if len(encoded.encode("utf-8")) > 32 * 1024:
            raise PlaybackBootstrapError(f"{field_name} exceeds 32 KiB")
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise PlaybackBootstrapError(f"{field_name} is not valid JSON: {_error_text(error)}") from error


def _validate_playback_metadata(value: object, config: PlaybackBootstrapConfig) -> None:
    """Playback slot metadataの型と全Fieldを厳密に照合する。"""

    metadata = _strict_object(value, PLAYBACK_SLOT_METADATA_FIELDS, "Playback slot metadata")
    if type(metadata["contract_version"]) is not int or metadata["contract_version"] != 1:
        raise PlaybackBootstrapError("Playback slot metadata contract_version must be integer 1")
    if type(metadata["channel_id"]) is not str or metadata["channel_id"] != config.channel_id:
        raise PlaybackBootstrapError("Playback slot metadata channel_id does not match config")
    if type(metadata["playback_schema"]) is not str or metadata["playback_schema"] != PLAYBACK_SCHEMA:
        raise PlaybackBootstrapError("Playback slot metadata playback_schema does not match Playback")
    wire_timebase = _strict_object(metadata["wire_timebase"], frozenset({"rate_num", "rate_den"}), "Playback wire_timebase")
    if (
        type(wire_timebase["rate_num"]) is not int
        or type(wire_timebase["rate_den"]) is not int
        or wire_timebase["rate_num"] != 120000
        or wire_timebase["rate_den"] != 1
    ):
        raise PlaybackBootstrapError("Playback slot metadata wire_timebase must be exactly 120000/1")


def _deadline(timeout: float) -> float:
    """現在時刻から有限のbootstrap deadlineを作る。"""

    now = time.monotonic()
    if not math.isfinite(now):
        raise PlaybackBootstrapError("monotonic clock returned a non-finite value")
    return now + timeout


def _message_id(value: object, name: str) -> str:
    """Client操作が返すmessage IDを検証する。"""

    if not isinstance(value, str) or not value:
        raise PlaybackBootstrapError(f"{name} must return a non-empty message ID")
    return value


def _identifier(value: object, name: str) -> str:
    return _validate_identifier(value, name, PlaybackBootstrapError)


_error_text = _bounded_error_message


__all__ = (
    "BROKER_PEER_ID",
    "ConnectionFactory",
    "PLAYBACK_SLOT_METADATA_FIELDS",
    "SLOT_DESCRIPTOR_FIELDS",
    "SLOT_DESCRIPTOR_SCHEMA",
    "SLOT_JOIN_SCHEMA",
    "PlaybackBootstrapConfig",
    "PlaybackBootstrapError",
    "bootstrap_playback_session",
)
