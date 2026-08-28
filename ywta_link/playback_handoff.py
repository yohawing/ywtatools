"""Playback操作に伴うAuthority handoffを束ねるDCC非依存Coordinator。"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from typing import Callable

from .authority import (
    AUTHORITY_ACCEPTED_SCHEMA,
    AUTHORITY_REJECTED_SCHEMA,
    AUTHORITY_REQUEST_SCHEMA,
    AuthorityHandoffRequest,
    AuthorityHandoffTracker,
)
from .authority_transport import AuthorityHandoffTransport
from .frame import Frame
from .playback_controller import PlaybackController
from .playback_host import PlaybackHostEvent, PlaybackHostSnapshot


class PlaybackHandoffError(RuntimeError):
    """Playback handoff Coordinatorの設定、状態、または依存component失敗を表す。"""


class PlaybackHandoffThreadError(PlaybackHandoffError):
    """Coordinatorをowner thread以外から操作したことを表す。"""


@dataclass(frozen=True)
class PlaybackHandoffErrorInfo:
    """Failed状態へ保存する型名と上限付きmessage。"""

    exception_type: str
    message: str


@dataclass(frozen=True)
class PlaybackHandoffStatus:
    """Coordinatorの軽量な状態snapshot。"""

    pending: bool
    failed: bool
    closed: bool
    error: PlaybackHandoffErrorInfo | None


class PlaybackHandoffCoordinator:
    """Playback eventとAuthority handoffの順序をMain Thread上で管理する。

    非AuthorityのHost eventは最新一件だけを保持し、Accepted control publishを受信するまで
    Controllerへ渡さない。CoordinatorはClient、Transport、Controllerを所有せず、既存の
    Runtimeがcomponent lifecycleを管理する。
    """

    def __init__(
        self,
        peer_id: str,
        channel_id: str,
        tracker: AuthorityHandoffTracker,
        authority_transport: AuthorityHandoffTransport,
        controller: PlaybackController,
        initial_snapshot: PlaybackHostSnapshot,
        rollback_apply: Callable[[PlaybackHostSnapshot], object],
        handoff_timeout: float,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """handoff対象とrollback基準を検証してowner threadを記録する。"""

        self._peer_id = _identifier(peer_id, "peer_id")
        self._channel_id = _identifier(channel_id, "channel_id")
        if type(tracker) is not AuthorityHandoffTracker:
            raise PlaybackHandoffError("tracker must be exactly an AuthorityHandoffTracker")
        if type(authority_transport) is not AuthorityHandoffTransport:
            raise PlaybackHandoffError("authority_transport must be exactly an AuthorityHandoffTransport")
        if type(controller) is not PlaybackController:
            raise PlaybackHandoffError("controller must be exactly a PlaybackController")
        if not isinstance(initial_snapshot, PlaybackHostSnapshot):
            raise PlaybackHandoffError("initial_snapshot must be a PlaybackHostSnapshot")
        if not callable(rollback_apply):
            raise PlaybackHandoffError("rollback_apply must be callable")
        if not _positive_finite(handoff_timeout):
            raise PlaybackHandoffError("handoff_timeout must be a positive finite number")
        if not callable(monotonic_clock):
            raise PlaybackHandoffError("monotonic_clock must be callable")
        if authority_transport.tracker is not tracker:
            raise PlaybackHandoffError("authority_transport must use the supplied tracker")
        if authority_transport.session_id != tracker.session_id:
            raise PlaybackHandoffError("authority_transport session does not match tracker")

        try:
            tracker.state_for(self._channel_id)
        except Exception as error:
            raise PlaybackHandoffError(f"invalid channel_id: {_error_message(error)}") from error

        self._tracker = tracker
        self._authority_transport = authority_transport
        self._controller = controller
        self._baseline = initial_snapshot
        self._rollback_apply = rollback_apply
        self._handoff_timeout = float(handoff_timeout)
        self._clock = monotonic_clock
        self._owner_thread_id = threading.get_ident()
        self._status_lock = threading.Lock()
        self._pending_deadline: float | None = None
        self._retained_event: PlaybackHostEvent | None = None
        self._closed = False
        self._failed = False
        self._error: PlaybackHandoffErrorInfo | None = None

    @property
    def status(self) -> PlaybackHandoffStatus:
        """Coordinatorの状態をthread-safeに観測する。"""

        with self._status_lock:
            return PlaybackHandoffStatus(
                pending=self._pending_deadline is not None,
                failed=self._failed,
                closed=self._closed,
                error=self._error,
            )

    def handle_host_event(self, event: PlaybackHostEvent) -> bool:
        """Host eventをAuthority状態に応じてpublishまたはhandoff要求へ変換する。"""

        self._require_owner()
        self._require_usable()
        if not isinstance(event, PlaybackHostEvent):
            raise PlaybackHandoffError("event must be a PlaybackHostEvent")

        try:
            state = self._tracker.state_for(self._channel_id)
            if state.authority == self._peer_id:
                result = self._controller.handle_host_event(event)
                if result is not True:
                    return False
                self._baseline = event.snapshot
                return True

            self._retained_event = event
            if self._tracker.pending_for(self._channel_id) is not None:
                return False
            request = AuthorityHandoffRequest(
                session_id=self._tracker.session_id,
                channel_id=self._channel_id,
                current_authority=state.authority,
                next_authority=self._peer_id,
                expected_authority_revision=state.revision,
                change_id=event.snapshot.change_id,
            )
            self._authority_transport.request_handoff(request)
            self._pending_deadline = self._deadline()
            return False
        except Exception as error:
            self._fail(error)
            raise self._public_error("handle_host_event failed", error) from error

    def handle_authority_frame(self, frame: Frame) -> bool:
        """Authority frameをTransportへ委譲し、必要なhandoff後処理だけを行う。"""

        self._require_owner()
        self._require_usable()
        if type(frame) is not Frame:
            raise PlaybackHandoffError("frame must be exactly a Frame")

        before_pending = self._tracker.pending_for(self._channel_id)
        try:
            handled = self._authority_transport.handle_frame(frame)
            if handled is not True:
                return False

            envelope = frame.envelope
            if envelope.type == "request" and envelope.schema == AUTHORITY_REQUEST_SCHEMA:
                self._accept_inbound_request()
                return True

            after_pending = self._tracker.pending_for(self._channel_id)
            after_state = self._tracker.state_for(self._channel_id)
            if envelope.type == "response" and envelope.schema == AUTHORITY_ACCEPTED_SCHEMA:
                # Accepted target responseはTrackerを変更しないため何もしない。
                return True
            if envelope.type == "response" and envelope.schema == AUTHORITY_REJECTED_SCHEMA:
                if before_pending is not None and after_pending is None:
                    self._restore_and_discard()
                return True
            if envelope.type == "publish" and envelope.schema == AUTHORITY_ACCEPTED_SCHEMA:
                self._handle_accepted_publish(frame, before_pending, after_pending, after_state)
            return True
        except Exception as error:
            self._fail(error)
            raise self._public_error("handle_authority_frame failed", error) from error

    def observe_authoritative_snapshot(self, snapshot: PlaybackHostSnapshot) -> None:
        """remote apply成功後のsnapshotを次回rollback基準として記録する。"""

        self._require_owner()
        self._require_usable()
        if not isinstance(snapshot, PlaybackHostSnapshot):
            raise PlaybackHandoffError("snapshot must be a PlaybackHostSnapshot")
        self._baseline = snapshot

    def poll_timeout(self) -> bool:
        """pending handoffの期限を確認し、期限切れならrollbackしてFailedにする。"""

        self._require_owner()
        self._require_usable()
        if self._pending_deadline is None:
            return False
        try:
            now = self._clock()
            if not isinstance(now, (int, float)) or isinstance(now, bool) or not math.isfinite(float(now)):
                raise PlaybackHandoffError("monotonic_clock must return a finite number")
            if float(now) < self._pending_deadline:
                return False
            self._restore_and_discard()
            error = PlaybackHandoffError("Authority handoff timed out")
            self._fail(error)
            return True
        except Exception as error:
            self._fail(error)
            raise self._public_error("poll_timeout failed", error) from error

    def close(self) -> bool:
        """保留eventとdeadlineだけを一度破棄し、borrowed componentは終了しない。"""

        self._require_owner()
        with self._status_lock:
            if self._closed:
                return False
            self._closed = True
        self._retained_event = None
        self._pending_deadline = None
        return True

    def _accept_inbound_request(self) -> None:
        """Transportが登録した現在channelのrequestを即時acceptする。"""

        state = self._tracker.state_for(self._channel_id)
        pending = self._tracker.pending_for(self._channel_id)
        if state.authority != self._peer_id or pending is None:
            return
        self._authority_transport.accept_handoff(pending.request)

    def _handle_accepted_publish(
        self,
        frame: Frame,
        before_pending: object,
        after_pending: object,
        after_state: object,
    ) -> None:
        """Accepted fan-out後のlocal request成功またはwinnerを処理する。"""

        if before_pending is None or after_pending is not None:
            return
        if getattr(after_state, "authority", None) != self._peer_id:
            self._restore_and_discard()
            return
        request_message_id = getattr(before_pending, "request_message_id", None)
        if frame.envelope.correlation_id != request_message_id:
            self._restore_and_discard()
            return
        event = self._retained_event
        self._pending_deadline = None
        if event is None:
            return
        result = self._controller.handle_host_event(event)
        if result is not True:
            raise PlaybackHandoffError("accepted handoff event was not published")
        self._baseline = event.snapshot
        self._retained_event = None

    def _restore_and_discard(self) -> None:
        """保存したbaselineをHostへ戻し、保留中のeventを破棄する。"""

        self._rollback_apply(self._baseline)
        self._retained_event = None
        self._pending_deadline = None

    def _deadline(self) -> float:
        """注入clockから有限なhandoff期限を計算する。"""

        now = self._clock()
        if not isinstance(now, (int, float)) or isinstance(now, bool) or not math.isfinite(float(now)):
            raise PlaybackHandoffError("monotonic_clock must return a finite number")
        return float(now) + self._handoff_timeout

    def _require_usable(self) -> None:
        """closeまたはFailed後の操作を拒否する。"""

        with self._status_lock:
            if self._closed:
                raise PlaybackHandoffError("PlaybackHandoffCoordinator is closed")
            if self._failed:
                raise PlaybackHandoffError("PlaybackHandoffCoordinator has failed")

    def _require_owner(self) -> None:
        """操作threadを生成元threadに限定する。"""

        if threading.get_ident() != self._owner_thread_id:
            raise PlaybackHandoffThreadError("PlaybackHandoffCoordinator operation must run on its owner thread")

    def _fail(self, error: BaseException) -> None:
        """最初の失敗原因だけを上限付きstatusへ保存する。"""

        with self._status_lock:
            if not self._failed:
                self._failed = True
                self._error = PlaybackHandoffErrorInfo(type(error).__name__, _error_message(error))

    @staticmethod
    def _public_error(prefix: str, error: BaseException) -> PlaybackHandoffError:
        """内部例外をCoordinator境界の型付き例外へ変換する。"""

        return PlaybackHandoffError(f"{prefix}: {_error_message(error)}")


def _identifier(value: object, field_name: str) -> str:
    """空白だけでないUTF-8文字列を識別子として受け入れる。"""

    if not isinstance(value, str) or not value or not value.strip():
        raise PlaybackHandoffError(f"{field_name} must be a non-whitespace string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise PlaybackHandoffError(f"{field_name} must be valid UTF-8") from error
    return value


def _positive_finite(value: object) -> bool:
    """boolを除く正の有限数を検証する。"""

    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
        and float(value) > 0
    )


def _error_message(error: BaseException) -> str:
    """例外messageを安全に1024文字へ制限する。"""

    try:
        return str(error)[:1024]
    except Exception:
        return "<unprintable exception>"


__all__ = (
    "PlaybackHandoffCoordinator",
    "PlaybackHandoffError",
    "PlaybackHandoffErrorInfo",
    "PlaybackHandoffStatus",
    "PlaybackHandoffThreadError",
)
