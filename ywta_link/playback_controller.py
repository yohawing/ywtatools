"""DCC非依存なPlayback Hostとwireの同期Controller。"""

from __future__ import annotations

import threading
import weakref
from dataclasses import dataclass
from typing import Callable

from .errors import AuthorityViolation
from .playback import Playback, PlaybackEchoGuard
from .playback_host import PlaybackHostEvent, PlaybackHostSnapshot
from .playback_mapping import PlaybackTimeMapper


class PlaybackControllerError(RuntimeError):
    """Playback Controllerの設定または状態が不正であることを表す。"""


class PlaybackControllerThreadError(PlaybackControllerError):
    """Controllerをowner thread以外から操作したことを表す。"""


@dataclass(frozen=True)
class PlaybackControllerErrorInfo:
    """Failed状態へ遷移した原因の型名と上限付きmessage。"""

    exception_type: str
    message: str


@dataclass(frozen=True)
class PlaybackControllerStatus:
    """Controllerの現時点状態を軽量に観測するsnapshot。"""

    closed: bool
    failed: bool
    error: PlaybackControllerErrorInfo | None


AuthorityProvider = Callable[[str], str]
PlaybackPublisher = Callable[[Playback], object]
PlaybackHostApply = Callable[[PlaybackHostSnapshot], None]

_CLAIMED_GUARDS: weakref.WeakSet[PlaybackEchoGuard] = weakref.WeakSet()
_CLAIMED_GUARDS_LOCK = threading.Lock()


class PlaybackController:
    """Playback同期のsingle-writer、mapping、echo抑止を束ねる。"""

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
        """owner threadを記録して、再利用不能なControllerを初期化する。"""

        self._peer_id = _identifier(peer_id, "peer_id")
        self._channel_id = _identifier(channel_id, "channel_id")
        if not isinstance(mapper, PlaybackTimeMapper):
            raise PlaybackControllerError("mapper must be a PlaybackTimeMapper")
        if not callable(authority_provider):
            raise PlaybackControllerError("authority_provider must be callable")
        if not callable(publisher):
            raise PlaybackControllerError("publisher must be callable")
        if not callable(host_apply):
            raise PlaybackControllerError("host_apply must be callable")
        if echo_guard is not None and not isinstance(echo_guard, PlaybackEchoGuard):
            raise PlaybackControllerError("echo_guard must be a PlaybackEchoGuard or None")

        self._mapper = mapper
        self._authority_provider = authority_provider
        self._publisher = publisher
        self._host_apply = host_apply
        # 注入時もこのControllerへ所有権を移す。close後に別Sessionへ再利用してはならない。
        self._echo_guard = PlaybackEchoGuard() if echo_guard is None else echo_guard
        _claim_guard(self._echo_guard)
        self._owner_thread_id = threading.get_ident()
        self._closed = False
        self._failed = False
        self._error: PlaybackControllerErrorInfo | None = None
        self._status_lock = threading.Lock()
        self._active_operation: str | None = None

    @property
    def status(self) -> PlaybackControllerStatus:
        """Controllerの状態をowner thread以外からも観測できる。"""

        with self._status_lock:
            return PlaybackControllerStatus(self._closed, self._failed, self._error)

    def handle_host_event(self, event: PlaybackHostEvent, origin_peer_id: str | None = None) -> bool:
        """Host eventをAuthority確認後にwireへpublishする。

        `origin_peer_id`を省略したeventはlocal操作として扱う。Remote applyに起因する
        callbackは、そのremote originを渡すことでEchoGuardによりpublishを抑止できる。
        Authorityでないlocal peerのeventはFalseを返し、publisherを呼び出さない。
        """

        self._require_owner()
        if not isinstance(event, PlaybackHostEvent):
            raise PlaybackControllerError("event must be a PlaybackHostEvent")
        if not self._usable():
            return False
        origin = self._peer_id if origin_peer_id is None else _identifier(origin_peer_id, "origin_peer_id")

        if self._active_operation == "publish":
            self._fail_reentrant("handle_host_event")

        if self._echo_guard is not None:
            try:
                if not self._echo_guard.should_publish(origin, event.snapshot.change_id):
                    return False
            except Exception as exc:
                self._mark_failed(exc)
                raise

        if self._active_operation is not None:
            self._fail_reentrant("handle_host_event")

        if self._authority() != self._peer_id:
            return False

        try:
            playback = self._mapper.to_playback(event.snapshot)
            self._active_operation = "publish"
            self._publisher(playback)
        except Exception as exc:
            self._mark_failed(exc)
            raise
        finally:
            self._active_operation = None
        return True

    def apply_remote(self, origin_peer_id: str, playback: Playback) -> bool:
        """Authority由来のPlaybackをHostへ適用する。

        現在Authorityでないoriginは`AuthorityViolation`として拒否する。local peer自身を
        originにした入力はloopbackとして無視し、Falseを返す。Host適用直前にEchoGuardへ
        remote identityを記録するため、同一callbackを即時処理しても再publishされない。
        """

        self._require_owner()
        if not self._usable():
            return False
        if self._active_operation is not None:
            self._fail_reentrant("apply_remote")
        origin = _identifier(origin_peer_id, "origin_peer_id")
        if not isinstance(playback, Playback):
            raise PlaybackControllerError("playback must be a Playback")
        if origin == self._peer_id:
            return False

        authority = self._authority()
        if origin != authority:
            raise AuthorityViolation(f"origin is not authority for channel: {self._channel_id!r}")

        try:
            snapshot = self._mapper.to_host_snapshot(playback)
            if self._echo_guard is not None:
                self._echo_guard.remember_remote(origin, playback.change_id)
            self._active_operation = "apply"
            self._host_apply(snapshot)
        except Exception as exc:
            self._mark_failed(exc)
            raise
        finally:
            self._active_operation = None
        return True

    def close(self) -> bool:
        """Controllerを閉じ、GuardとSession stateを破棄する。

        初回closeではTrue、既に閉じている場合はFalseを返す。close後のControllerは
        再利用できず、すべての同期操作がFalseを返す。
        """

        self._require_owner()
        if self._active_operation is not None:
            self._fail_reentrant("close")
        with self._status_lock:
            if self._closed:
                return False
            self._closed = True
            self._echo_guard = None
        return True

    def _usable(self) -> bool:
        """ClosedまたはFailedでないときだけ操作を許可する。"""

        with self._status_lock:
            return not self._closed and not self._failed

    def _authority(self) -> str:
        """Authority providerを呼び出し、異常時はFailedへ遷移する。"""

        try:
            authority = self._authority_provider(self._channel_id)
            return _identifier(authority, "authority")
        except Exception as exc:
            self._mark_failed(exc)
            raise

    def _mark_failed(self, error: Exception) -> None:
        """例外本体を保持せず、軽量原因だけを記録してFailedへ遷移する。"""

        try:
            message = str(error)
        except Exception:
            message = "<unprintable exception>"
        if len(message) > 1024:
            message = message[:1024]
        with self._status_lock:
            if not self._closed:
                self._failed = True
                self._error = PlaybackControllerErrorInfo(type(error).__name__, message)

    def _require_owner(self) -> None:
        """操作threadをController生成元に限定する。"""

        if threading.get_ident() != self._owner_thread_id:
            raise PlaybackControllerThreadError("PlaybackController operation must run on its owner thread")

    def _fail_reentrant(self, operation: str) -> None:
        """許可されない同期再入をFailedとして拒否する。"""

        error = PlaybackControllerError(f"{operation} cannot run during {self._active_operation}")
        self._mark_failed(error)
        raise error


def _claim_guard(guard: PlaybackEchoGuard) -> None:
    """Echo Guardを一つのControllerへだけ所有させる。"""

    with _CLAIMED_GUARDS_LOCK:
        if guard in _CLAIMED_GUARDS:
            raise PlaybackControllerError("echo_guard is already owned by another Controller")
        _CLAIMED_GUARDS.add(guard)


def _identifier(value: object, field_name: str) -> str:
    """空白だけでないUTF-8文字列を識別子として受け入れる。"""

    if not isinstance(value, str) or not value or not value.strip():
        raise PlaybackControllerError(f"{field_name} must be a non-whitespace string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise PlaybackControllerError(f"{field_name} must be valid UTF-8") from exc
    return value


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
