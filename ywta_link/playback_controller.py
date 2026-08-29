"""DCC非依存なPlayback Hostとwireの同期Controller。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ._snapshot_sync import SnapshotController
from .playback import Playback, PlaybackEchoGuard
from .playback_host import PlaybackHostEvent, PlaybackHostSnapshot
from .playback_mapping import PlaybackTimeMapper


class PlaybackControllerError(RuntimeError):
    """Playback Controllerの設定または状態が不正であることを表す。"""


class PlaybackControllerThreadError(PlaybackControllerError):
    """Controllerをowner thread以外から操作したことを表す。"""


@dataclass(frozen=True)
class PlaybackControllerErrorInfo:
    """Failed状態へ遷移した原因。"""

    exception_type: str
    message: str


@dataclass(frozen=True)
class PlaybackControllerStatus:
    """Controllerの現時点状態。"""

    closed: bool
    failed: bool
    error: PlaybackControllerErrorInfo | None


AuthorityProvider = Callable[[str], str]
PlaybackPublisher = Callable[[Playback], object]
PlaybackHostApply = Callable[[PlaybackHostSnapshot], None]


class PlaybackController(SnapshotController):
    """Playback同期のsingle-writer、mapping、echo抑止を束ねる。"""

    snapshot_type = Playback
    local_type = PlaybackHostEvent
    guard_type = PlaybackEchoGuard
    error_type = PlaybackControllerError
    thread_error_type = PlaybackControllerThreadError
    label = "Playback"

    def __init__(
        self,
        peer_id: str,
        channel_id: str,
        mapper: PlaybackTimeMapper,
        authority_provider: AuthorityProvider,
        publisher: PlaybackPublisher,
        host_apply: PlaybackHostApply,
        echo_guard: PlaybackEchoGuard | None = None,
    ) -> None:
        if not isinstance(mapper, PlaybackTimeMapper):
            raise PlaybackControllerError("mapper must be a PlaybackTimeMapper")
        if echo_guard is not None and not isinstance(echo_guard, PlaybackEchoGuard):
            raise PlaybackControllerError("echo_guard must be a PlaybackEchoGuard or None")
        guard = PlaybackEchoGuard() if echo_guard is None else echo_guard
        self._mapper = mapper
        super().__init__(peer_id, channel_id, authority_provider, publisher, host_apply, guard)
        self._echo_guard = self._guard

    @property
    def status(self) -> PlaybackControllerStatus:
        status = super().status
        error = status.error
        detail = None if error is None else PlaybackControllerErrorInfo(error.exception_type, error.message)
        return PlaybackControllerStatus(status.closed, status.failed, detail)

    def handle_host_event(self, event: PlaybackHostEvent, origin_peer_id: str | None = None) -> bool:
        """Host eventをAuthority確認後にwireへpublishする。"""

        return self.handle_host_change(event, origin_peer_id)

    def _to_wire(self, value: PlaybackHostEvent) -> Playback:
        return self._mapper.to_playback(value.snapshot)

    def _to_host(self, value: Playback) -> PlaybackHostSnapshot:
        return self._mapper.to_host_snapshot(value)

    def _change_id(self, value: Playback | PlaybackHostEvent) -> str:
        return value.change_id if isinstance(value, Playback) else value.snapshot.change_id

    def _guard_should_publish(self, origin: str, change_id: str) -> bool:
        return self._guard.should_publish(origin, change_id)

    def _guard_remember(self, origin: str, change_id: str) -> None:
        self._guard.remember_remote(origin, change_id)


__all__ = (
    "AuthorityProvider",
    "PlaybackController",
    "PlaybackControllerError",
    "PlaybackControllerErrorInfo",
    "PlaybackHostApply",
    "PlaybackPublisher",
    "PlaybackControllerStatus",
    "PlaybackControllerThreadError",
)
