"""Sync Session状態機械とChannel revision追跡。"""

from __future__ import annotations

from enum import Enum
from typing import Mapping

from .contract import SyncContract
from .errors import AuthorityViolation, InvalidStateTransition, StaleRevision, ValidationError


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
    """Authority以外と古いrevisionをAdapter到達前に拒否する。"""

    def __init__(self, contract: SyncContract | Mapping[str, str]) -> None:
        """ContractまたはChannelとAuthorityの対応から追跡器を作る。"""

        if isinstance(contract, SyncContract):
            self._authorities = {channel.channel_id: channel.authority for channel in contract.channels}
        else:
            self._authorities = dict(contract)
        if not self._authorities or any(
            not isinstance(channel_id, str) or not channel_id or not isinstance(authority, str) or not authority
            for channel_id, authority in self._authorities.items()
        ):
            raise ValidationError("channel authorities must be non-empty strings")
        self._revisions: dict[str, int] = {}

    def accept(self, channel_id: str, sender: str, revision: int) -> int:
        """Authorityからの新しいrevisionだけを記録する。"""

        authority = self._authorities.get(channel_id)
        if authority is None:
            raise ValidationError(f"unknown channel: {channel_id!r}")
        if sender != authority:
            raise AuthorityViolation(f"sender is not authority for channel: {channel_id!r}")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise ValidationError("revision must be a non-negative integer")
        previous = self._revisions.get(channel_id)
        if previous is not None and revision <= previous:
            raise StaleRevision(f"revision {revision} is not newer than accepted revision {previous}")
        self._revisions[channel_id] = revision
        return revision

    def revision_for(self, channel_id: str) -> int | None:
        """最後に受理したrevisionを返す。"""

        if channel_id not in self._authorities:
            raise ValidationError(f"unknown channel: {channel_id!r}")
        return self._revisions.get(channel_id)
