"""Sync Session状態機械とChannel revision追跡。"""

from __future__ import annotations

import threading
from enum import Enum
from typing import Any, Mapping

from .contract import SyncContract
from .errors import AuthorityViolation, InvalidStateTransition, StaleRevision, ValidationError, _validate_identifier


class SessionState(str, Enum):
    """Sync Sessionで許可される状態。"""

    DRAFT = "Draft"
    NEGOTIATING = "Negotiating"
    ACTIVE = "Active"
    CLOSING = "Closing"
    CLOSED = "Closed"
    FAILED = "Failed"


_ALLOWED_TRANSITIONS = {
    SessionState.DRAFT: frozenset({SessionState.NEGOTIATING}),
    SessionState.NEGOTIATING: frozenset({SessionState.ACTIVE, SessionState.FAILED}),
    SessionState.ACTIVE: frozenset({SessionState.CLOSING, SessionState.FAILED}),
    SessionState.CLOSING: frozenset({SessionState.CLOSED, SessionState.FAILED}),
    SessionState.CLOSED: frozenset(),
    SessionState.FAILED: frozenset(),
}


class SyncSession:
    """副作用を持たない短命なSync Sessionの状態機械。"""

    def __init__(self, contract: SyncContract) -> None:
        """Draft状態のSessionを作成する。"""

        self.contract = contract
        self.state = SessionState.DRAFT

    def transition(self, next_state: SessionState | str) -> SessionState:
        """仕様で許可された次状態へ遷移する。"""

        try:
            resolved_state = SessionState(next_state)
        except ValueError as exc:
            raise InvalidStateTransition(f"unknown state: {next_state!r}") from exc
        if resolved_state not in _ALLOWED_TRANSITIONS[self.state]:
            raise InvalidStateTransition(f"cannot transition from {self.state.value} to {resolved_state.value}")
        self.state = resolved_state
        return self.state


class ChannelRevisionTracker:
    """Authorityとcontent revisionの検証を同じlockで一元管理する。"""

    def __init__(
        self,
        contract: SyncContract | Mapping[str, str],
        *,
        initial_authority_revisions: Mapping[str, int] | None = None,
    ) -> None:
        """ContractまたはChannelとAuthorityの対応から追跡器を作る。

        ``initial_authority_revisions`` は、snapshotで得たcontrol-plane
        revisionを構築時に注入するためのものであり、Channel keyの過不足を
        許可しない。
        """

        if isinstance(contract, SyncContract):
            self._authorities = {channel.channel_id: channel.authority for channel in contract.channels}
        else:
            if not isinstance(contract, Mapping):
                raise ValidationError("contract must be a SyncContract or channel authority mapping")
            self._authorities = dict(contract)
        if not self._authorities or any(
            not _identifier(channel_id, "channel_id") or not _identifier(authority, "authority")
            for channel_id, authority in self._authorities.items()
        ):
            raise ValidationError("channel authorities must be non-empty strings")
        self._lock = threading.RLock()
        self._revisions: dict[str, int] = {}
        self._authority_revisions = _initial_revisions(
            self._authorities,
            initial_authority_revisions,
        )

    @property
    def lock(self) -> Any:
        """Authority handoffとcontent updateを同一atomic sectionへ束ねるlockを返す。"""

        return self._lock

    def accept(self, channel_id: str, sender: str, revision: int) -> int:
        """Authorityからの新しいrevisionだけを記録する。"""

        with self._lock:
            authority = self._authority_for_unlocked(channel_id)
            sender = _identifier(sender, "sender")
            if sender != authority:
                raise AuthorityViolation(f"sender is not authority for channel: {channel_id!r}")
            _content_revision(revision)
            previous = self._revisions.get(channel_id)
            if previous is not None and revision <= previous:
                raise StaleRevision(f"revision {revision} is not newer than accepted revision {previous}")
            self._revisions[channel_id] = revision
            return revision

    def accept_content(self, channel_id: str, sender: str, revision: int) -> int:
        """現在Authorityからのcontent revisionを受理するfacade。"""

        return self.accept(channel_id, sender, revision)

    def authority_for(self, channel_id: str) -> str:
        """Channelの現在Authorityを返す。"""

        with self._lock:
            return self._authority_for_unlocked(channel_id)

    def authority_revision_for(self, channel_id: str) -> int:
        """Channelのcontrol-plane authority revisionを返す。"""

        with self._lock:
            self._authority_for_unlocked(channel_id)
            return self._authority_revisions[channel_id]

    def channels(self) -> tuple[str, ...]:
        """追跡中Channel IDを辞書順のsnapshotで返す。"""

        with self._lock:
            return tuple(sorted(self._authorities))

    def transfer_authority(
        self,
        channel_id: str,
        current_authority: str,
        next_authority: str,
        expected_authority_revision: int,
    ) -> int:
        """期待revisionを検証し、Authorityと専用revisionをatomicに更新する。"""

        _identifier(current_authority, "current_authority")
        _identifier(next_authority, "next_authority")
        if current_authority == next_authority:
            raise ValidationError("current_authority and next_authority must differ")
        _non_negative_revision(expected_authority_revision, "expected_authority_revision")
        with self._lock:
            authority = self._authority_for_unlocked(channel_id)
            current_revision = self._authority_revisions[channel_id]
            if expected_authority_revision != current_revision:
                raise StaleRevision(
                    f"authority revision {expected_authority_revision} is not current revision {current_revision}"
                )
            if current_authority != authority:
                raise AuthorityViolation(f"current authority is not current for channel: {channel_id!r}")
            new_revision = current_revision + 1
            self._authorities[channel_id] = next_authority
            self._authority_revisions[channel_id] = new_revision
            return new_revision

    def revision_for(self, channel_id: str) -> int | None:
        """最後に受理したrevisionを返す。"""

        with self._lock:
            self._authority_for_unlocked(channel_id)
            return self._revisions.get(channel_id)

    def _authority_for_unlocked(self, channel_id: str) -> str:
        """lock取得済みのauthority lookup。"""

        if not isinstance(channel_id, str) or not channel_id or not channel_id.strip():
            raise ValidationError("channel_id must be a non-whitespace string")
        try:
            return self._authorities[channel_id]
        except KeyError as exc:
            raise ValidationError(f"unknown channel: {channel_id!r}") from exc


def _identifier(value: object, field_name: str) -> str:
    return _validate_identifier(value, field_name, ValidationError)


def _content_revision(value: object) -> int:
    """content revisionの入力を検証する。"""

    return _non_negative_revision(value, "revision")


def _non_negative_revision(value: object, field_name: str) -> int:
    """boolを除く0以上の整数を検証する。"""

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValidationError(f"{field_name} must be a non-negative integer")
    return value


def _initial_revisions(
    authorities: Mapping[str, str],
    revisions: Mapping[str, int] | None,
) -> dict[str, int]:
    """Channel keyを厳密に照合した初期authority revisionを作る。"""

    if revisions is None:
        return {channel_id: 0 for channel_id in authorities}
    if not isinstance(revisions, Mapping):
        raise ValidationError("initial_authority_revisions must be a mapping")
    if set(revisions) != set(authorities):
        raise ValidationError("initial_authority_revisions must contain exactly the contract channels")
    return {channel_id: _non_negative_revision(revisions[channel_id], "authority_revision") for channel_id in authorities}
