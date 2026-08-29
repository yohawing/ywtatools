"""Mayaの再生状態をYWTA Link Adapter境界へ投影する。"""

from __future__ import annotations

import math
import threading
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from ywta_link.playback_host import (
    PlaybackHostEvent,
    PlaybackHostEventKind,
    PlaybackHostRange,
    PlaybackHostSnapshot,
)

try:
    import maya.api.OpenMaya as _OPEN_MAYA
except ImportError:  # Maya外でのimportと依存注入テストを許可する。
    _OPEN_MAYA = None

try:
    import maya.api.OpenMayaAnim as _OPEN_MAYA_ANIM
except ImportError:  # Maya外でのimportと依存注入テストを許可する。
    _OPEN_MAYA_ANIM = None

try:
    import maya.cmds as _MAYA_CMDS
except ImportError:  # Maya外でのimportと依存注入テストを許可する。
    _MAYA_CMDS = None


class MayaPlaybackHostError(RuntimeError):
    """Maya Playback Host bridgeの設定または状態が不正である。"""


class MayaPlaybackHostUnavailableError(MayaPlaybackHostError):
    """Maya Python APIが利用できない。"""


MAYA_PLAYBACK_EVENTS = (
    "timeChanged",
    "playbackRangeChanged",
    "playbackSpeedChanged",
    "playbackModeChanged",
)


@dataclass(frozen=True)
class CallbackErrorStatus:
    """Maya callback内で隔離した最後の例外情報。"""

    callback: str
    exception_type: str
    message: str
    count: int


class MayaPlaybackHost:
    """Maya playback callbackの登録とMain Thread applyを担当する薄いbridge。

    `api`と`anim_control`を注入すればMaya外でも登録、callback、applyの境界を検証できる。
    Bridge自身はnetwork送信を行わず、local変更だけを`on_change`へ通知する。
    """

    def __init__(
        self,
        on_change: Callable[[PlaybackHostEvent], None],
        *,
        api: Any = None,
        anim_control: Any = None,
        time_unit: Any = None,
        time_unit_label: str | None = None,
        time_unit_label_provider: Callable[[], Any] | None = None,
        frame_step: float = 1.0,
        direction_query: Callable[[], Any] | None = None,
    ) -> None:
        """Maya API依存を解決し、所有Threadを記録する。"""

        if not callable(on_change):
            raise MayaPlaybackHostError("on_change must be callable")
        if time_unit_label_provider is not None and not callable(time_unit_label_provider):
            raise MayaPlaybackHostError("time_unit_label_provider must be callable")
        if direction_query is not None and not callable(direction_query):
            raise MayaPlaybackHostError("direction_query must be callable")
        if isinstance(frame_step, bool) or not isinstance(frame_step, (int, float)):
            raise MayaPlaybackHostError("frame_step must be a positive finite number")
        if not math.isfinite(float(frame_step)) or frame_step <= 0:
            raise MayaPlaybackHostError("frame_step must be a positive finite number")

        self._api = _OPEN_MAYA if api is None else api
        if self._api is None:
            raise MayaPlaybackHostUnavailableError("Maya Python API is unavailable; inject api and anim_control for tests")
        default_anim_api = _OPEN_MAYA_ANIM if api is None else self._api
        self._anim = getattr(default_anim_api, "MAnimControl", None) if anim_control is None else anim_control
        if self._anim is None:
            raise MayaPlaybackHostUnavailableError("MAnimControl is unavailable")

        self._on_change = on_change
        self._owner_thread_id = threading.get_ident()
        self._frame_step = frame_step
        if isinstance(time_unit, str):
            raise MayaPlaybackHostError("time_unit must be an MTime UI unit enum")
        self._time_unit = self._resolve_time_unit(time_unit)
        if self._time_unit is None or isinstance(self._time_unit, str):
            raise MayaPlaybackHostUnavailableError("MTime.uiUnit must provide an MTime UI unit enum")
        self._time_unit_label = self._resolve_time_unit_label(time_unit_label)
        if time_unit_label_provider is not None:
            self._time_unit_label_provider = time_unit_label_provider
        elif time_unit_label is not None and api is None:
            self._time_unit_label_provider = _default_time_unit_label_query
        else:
            self._time_unit_label_provider = None
        if direction_query is not None:
            self._direction_query = direction_query
        elif api is None:
            self._direction_query = _default_direction_query
        else:
            # 注入APIはfakeを含むため、実環境のmaya.cmdsを暗黙参照しない。
            self._direction_query = _none_direction_query
        self._callback_ids: list[Any] = []
        self._registered = False
        self._applying = False
        self._playing: bool | None = None
        self._last_direction = "forward"
        self._last_error: CallbackErrorStatus | None = None
        self._error_count = 0
        self._failed = False

    @property
    def registered(self) -> bool:
        """callbackが登録済みかを返す。"""

        return self._registered

    @property
    def callback_ids(self) -> tuple[Any, ...]:
        """登録済みcallback IDのimmutableなsnapshotを返す。"""

        return tuple(self._callback_ids)

    @property
    def last_error(self) -> CallbackErrorStatus | None:
        """隔離された最後のcallback例外を返す。"""

        return self._last_error

    @property
    def failed(self) -> bool:
        """同期を継続できないcallback境界の失敗を返す。"""

        return self._failed

    @property
    def time_unit(self) -> Any:
        """MTime constructorへ渡すUI unit enumを返す。"""

        return self._time_unit

    @property
    def time_unit_label(self) -> str:
        """snapshotへ出力するMaya time unit labelを返す。"""

        return self._time_unit_label

    def register(self) -> bool:
        """Maya callbacksを一度だけ登録する。"""

        self._assert_owner_thread("register")
        try:
            self._validate_time_unit_label()
        except BaseException as error:
            self._record_error("register", error)
            raise
        if self._registered:
            return False
        condition_message = getattr(self._api, "MConditionMessage", None)
        event_message = getattr(self._api, "MEventMessage", None)
        if condition_message is None or event_message is None:
            raise MayaPlaybackHostUnavailableError("MConditionMessage and MEventMessage are required")
        try:
            condition_id = condition_message.addConditionCallback("playingBack", self._condition_callback)
            self._callback_ids.append(condition_id)
            callbacks = {
                "timeChanged": self._time_changed_callback,
                "playbackRangeChanged": self._range_changed_callback,
                "playbackSpeedChanged": self._speed_changed_callback,
                "playbackModeChanged": self._mode_changed_callback,
            }
            for event_name, callback in callbacks.items():
                callback_id = event_message.addEventCallback(event_name, callback)
                self._callback_ids.append(callback_id)
            self._playing = bool(_member_value(self._anim, "isPlaying", False))
        except BaseException as exc:
            try:
                self._remove_callbacks_safely()
            except BaseException:
                # cleanup失敗時はIDを残し、unregister()で再試行できるpartial stateにする。
                self._registered = bool(self._callback_ids)
                raise MayaPlaybackHostError("Maya playback callback registration failed; callback cleanup failed") from exc
            self._callback_ids.clear()
            self._registered = False
            raise MayaPlaybackHostError("Maya playback callback registration failed") from exc

        self._registered = True
        return True

    def unregister(self) -> bool:
        """登録した全callbackをMMessage.removeCallbackで個別解除する。"""

        self._assert_owner_thread("unregister")
        if not self._callback_ids:
            self._registered = False
            return False
        try:
            self._remove_callbacks_safely()
        except BaseException as exc:
            raise MayaPlaybackHostError("Maya playback callback removal failed") from exc
        else:
            self._callback_ids.clear()
            self._registered = False
            self._playing = None
        return True

    close = unregister

    def apply(self, snapshot: PlaybackHostSnapshot) -> None:
        """Remote snapshotをMaya Main Threadへ適用する。

        適用中に発生するMaya callbackはlocal eventとして通知しない。Mayaのinclusiveな
        maxTimeへはwire `end_exclusive - frame_step`として変換する。
        """

        self._assert_owner_thread("apply")
        self._assert_healthy("apply")
        try:
            self._validate_time_unit_label()
        except BaseException as error:
            self._record_error("apply", error)
            raise
        if not isinstance(snapshot, PlaybackHostSnapshot):
            raise MayaPlaybackHostError("snapshot must be a PlaybackHostSnapshot")
        self._applying = True
        try:
            stop = getattr(self._anim, "stop", None)
            if not callable(stop):
                raise MayaPlaybackHostUnavailableError("MAnimControl.stop is unavailable")
            stop()
            set_min_max_time = getattr(self._anim, "setMinMaxTime", None)
            if not callable(set_min_max_time):
                raise MayaPlaybackHostUnavailableError("MAnimControl.setMinMaxTime is unavailable")
            start, end_inclusive = self.wire_range_to_maya(
                snapshot.playback_range,
                frame_step=self._frame_step,
            )
            set_min_max_time(self._make_mtime(start), self._make_mtime(end_inclusive))
            self._call_anim("setPlaybackSpeed", snapshot.speed)
            current_step = abs(float(_member_value(self._anim, "playbackBy", self._frame_step)))
            if not math.isfinite(current_step) or current_step == 0:
                current_step = float(self._frame_step)
            # 方向はplayForward/playBackwardだけで指定し、frame incrementは常に正数にする。
            self._call_anim("setPlaybackBy", current_step)
            self._call_anim("setPlaybackMode", self._mode_value(snapshot.loop_mode))
            self._call_anim("setCurrentTime", self._make_mtime(snapshot.position))
            if snapshot.state == "playing":
                self._play(snapshot.direction)
            self._playing = snapshot.state == "playing"
        finally:
            self._applying = False

    apply_snapshot = apply

    def snapshot(self) -> PlaybackHostSnapshot:
        """現在のMaya playback状態をMain Thread上で取得する。"""

        self._assert_owner_thread("snapshot")
        self._assert_healthy("snapshot")
        try:
            return self._read_snapshot()
        except BaseException as error:
            self._record_error("snapshot", error)
            raise

    @staticmethod
    def maya_range_to_wire(
        start: float | int,
        end_inclusive: float | int,
        *,
        frame_step: float = 1.0,
    ) -> PlaybackHostRange:
        """Maya inclusive rangeをwireの半開rangeへ変換する。"""

        _positive_number(frame_step, "frame_step")
        _finite_number(start, "start")
        _finite_number(end_inclusive, "end_inclusive")
        return PlaybackHostRange(start, end_inclusive + frame_step)

    @staticmethod
    def wire_range_to_maya(
        playback_range: PlaybackHostRange | Mapping[str, Any],
        *,
        frame_step: float = 1.0,
    ) -> tuple[float | int, float | int]:
        """wire半開rangeをMaya inclusive rangeへ戻す。"""

        _positive_number(frame_step, "frame_step")
        if not isinstance(playback_range, PlaybackHostRange):
            playback_range = PlaybackHostRange(
                playback_range["start"],
                playback_range["end_exclusive"],
            )
        return playback_range.start, playback_range.end_exclusive - frame_step

    def _condition_callback(self, state: Any, *_args: Any) -> None:
        """playingBack conditionをstart/stop eventへ変換する。"""

        self._invoke_callback("playingBack", lambda: self._handle_playing_back(bool(state)))

    def _handle_playing_back(self, playing: bool) -> None:
        """再生状態のedgeだけをeventとして通知する。"""

        previous = self._playing
        self._playing = playing
        if self._applying or previous == playing:
            return
        kind = PlaybackHostEventKind.PLAY_STARTED if playing else PlaybackHostEventKind.PLAY_STOPPED
        self._emit(kind)

    def _time_changed_callback(self, *_args: Any) -> None:
        """再生中の毎frame通知を抑止し、paused seekだけを通知する。"""

        self._invoke_callback("timeChanged", self._handle_time_changed)

    def _handle_time_changed(self) -> None:
        """timeChangedを再生状態に応じて処理する。"""

        # playingBack conditionが先に到着するHostでは、そのedgeを優先して毎Frameを抑止する。
        playing = self._playing is True or bool(_member_value(self._anim, "isPlaying", False))
        self._playing = playing
        if not playing and not self._applying:
            self._emit(PlaybackHostEventKind.PAUSED_SEEK)

    def _range_changed_callback(self, *_args: Any) -> None:
        """playbackRangeChangedを通知する。"""

        self._invoke_callback("playbackRangeChanged", lambda: self._emit(PlaybackHostEventKind.RANGE_CHANGED))

    def _speed_changed_callback(self, *_args: Any) -> None:
        """playbackSpeedChangedを通知する。"""

        self._invoke_callback("playbackSpeedChanged", lambda: self._emit(PlaybackHostEventKind.SPEED_CHANGED))

    def _mode_changed_callback(self, *_args: Any) -> None:
        """playbackModeChangedを通知する。"""

        self._invoke_callback("playbackModeChanged", lambda: self._emit(PlaybackHostEventKind.MODE_CHANGED))

    def _emit(self, kind: PlaybackHostEventKind) -> None:
        """current snapshotをimmutable eventとして安全に通知する。"""

        if self._failed or self._applying:
            return
        event = PlaybackHostEvent(kind=kind, snapshot=self._read_snapshot())
        try:
            self._on_change(event)
        except BaseException as exc:
            self._record_error(kind.value, exc)

    def _invoke_callback(self, callback_name: str, callback: Callable[[], None]) -> None:
        """Maya event loopへ例外を漏らさずcallbackを実行する。"""

        if self._failed:
            return
        try:
            callback()
        except BaseException as exc:
            self._record_error(callback_name, exc)

    def _read_snapshot(self) -> PlaybackHostSnapshot:
        """MAnimControlからMaya非依存のsnapshotを作る。"""

        self._validate_time_unit_label()
        current = _time_value(_member_value(self._anim, "currentTime"))
        minimum = _time_value(_member_value(self._anim, "minTime"))
        maximum = _time_value(_member_value(self._anim, "maxTime"))
        raw_playback_speed = _member_value(self._anim, "playbackSpeed", 1.0)
        try:
            playback_speed = float(raw_playback_speed)
        except (TypeError, ValueError, OverflowError):
            playback_speed = 1.0
        approximated_fields: tuple[str, ...] = ()
        if not math.isfinite(playback_speed) or playback_speed <= 0:
            playback_speed = 1.0
            approximated_fields = ("speed",)
        direction = self._query_direction()
        playing = self._playing is True or bool(_member_value(self._anim, "isPlaying", False))
        state = "playing" if playing else "paused"
        return PlaybackHostSnapshot(
            state=state,
            position=current,
            playback_range=self.maya_range_to_wire(minimum, maximum, frame_step=self._frame_step),
            speed=playback_speed,
            direction=direction,
            loop_mode=self._loop_mode_name(_member_value(self._anim, "playbackMode", None)),
            time_unit=self._time_unit_label,
            change_id=uuid.uuid4().hex,
            approximated_fields=approximated_fields,
        )

    def _make_mtime(self, value: float | int) -> Any:
        """現在UI unitのMTimeを構築する。"""

        mtime = getattr(self._api, "MTime", None)
        if mtime is None:
            return value
        try:
            return mtime(value, self._time_unit)
        except TypeError:
            return mtime(value)

    def _mode_value(self, loop_mode: str) -> Any:
        """Common loop意図をMaya playback modeへ変換する。"""

        names = {
            "once": "kPlaybackOnce",
            "loop": "kPlaybackLoop",
            "ping-pong": "kPlaybackOscillate",
        }
        name = names[loop_mode]
        value = getattr(self._anim, name, None)
        if value is None:
            value = getattr(getattr(self._api, "MAnimControl", object()), name, None)
        if value is None:
            raise MayaPlaybackHostUnavailableError(f"Maya playback mode constant {name} is unavailable")
        return value

    def _play(self, direction: str) -> None:
        """Maya 2024の方向別play APIで再生を開始する。"""

        method_name = "playBackward" if direction == "reverse" else "playForward"
        method = getattr(self._anim, method_name, None)
        if callable(method):
            method()
            return
        # fakeまたは旧API向けの注入境界。Maya 2024では上の方向別APIが使われる。
        self._call_anim("play")

    def _query_direction(self) -> str:
        """Maya commandのforward queryを使い、失敗時は直前の方向を維持する。"""

        try:
            value = self._direction_query()
        except BaseException as exc:
            self._record_error("direction_query", exc, terminal=False)
            return self._last_direction
        if isinstance(value, bool):
            self._last_direction = "forward" if value else "reverse"
        return self._last_direction

    def _loop_mode_name(self, value: Any) -> str:
        """Maya playback modeをCommon loop意図へ変換する。"""

        if value == getattr(self._anim, "kPlaybackLoop", object()):
            return "loop"
        if value == getattr(self._anim, "kPlaybackOscillate", object()):
            return "ping-pong"
        if value == getattr(self._api, "kPlaybackLoop", object()):
            return "loop"
        if value == getattr(self._api, "kPlaybackOscillate", object()):
            return "ping-pong"
        return "once"

    def _call_anim(self, name: str, *args: Any) -> None:
        """MAnimControl methodの存在を確認して呼び出す。"""

        method = getattr(self._anim, name, None)
        if not callable(method):
            raise MayaPlaybackHostUnavailableError(f"MAnimControl.{name} is unavailable")
        method(*args)

    def _remove_callbacks_safely(self) -> None:
        """登録済みIDをMMessageへ個別に渡し、成功IDを即時台帳から除外する。"""

        if not self._callback_ids:
            return
        message = getattr(self._api, "MMessage", None)
        remove = getattr(message, "removeCallback", None)
        if not callable(remove):
            raise MayaPlaybackHostUnavailableError("MMessage.removeCallback is unavailable")
        failures: list[BaseException] = []
        for callback_id in tuple(self._callback_ids):
            try:
                remove(callback_id)
            except BaseException as exc:
                failures.append(exc)
            else:
                self._callback_ids.remove(callback_id)
        if failures:
            raise failures[0]

    def _assert_owner_thread(self, operation: str) -> None:
        """Maya Main Thread以外からの操作を拒否する。"""

        if threading.get_ident() != self._owner_thread_id:
            raise MayaPlaybackHostError(f"{operation} must run on the Maya Main Thread")

    def _assert_healthy(self, operation: str) -> None:
        """terminal failure後の同期操作を拒否する。"""

        if self._failed:
            raise MayaPlaybackHostError(f"{operation} is unavailable after Playback Host failure")

    def _record_error(self, callback_name: str, error: BaseException, *, terminal: bool = True) -> None:
        """例外本体を保持せず、観測可能な軽量statusを更新する。"""

        if terminal:
            self._failed = True
        self._error_count += 1
        try:
            message = str(error)
        except BaseException:
            message = "<unprintable exception>"
        self._last_error = CallbackErrorStatus(
            callback=callback_name,
            exception_type=type(error).__name__,
            message=message[:1024],
            count=self._error_count,
        )

    def _resolve_time_unit(self, explicit: Any) -> Any:
        """指定がなければMaya UI unitを取得する。"""

        if explicit is not None:
            return explicit
        mtime = getattr(self._api, "MTime", None)
        ui_unit = getattr(mtime, "uiUnit", None)
        if callable(ui_unit):
            return ui_unit()
        return None

    def _resolve_time_unit_label(self, explicit: str | None) -> str:
        """MTime enumをsnapshot用のlabelへ変換し、明示labelを検証する。"""

        label = self._unit_label(self._time_unit) if explicit is None else explicit
        if not isinstance(label, str) or not label.strip():
            raise MayaPlaybackHostError("time_unit_label must be a non-empty string")
        return label

    def _validate_time_unit_label(self) -> None:
        """現在のMaya labelがcapture済みlabelから変化していないことを検証する。"""

        if self._time_unit_label_provider is None:
            return
        try:
            current = self._time_unit_label_provider()
        except BaseException as error:
            raise MayaPlaybackHostError("Maya time unit label query failed") from error
        if not isinstance(current, str) or not current.strip():
            raise MayaPlaybackHostError("current Maya time unit label is invalid")
        if current != self._time_unit_label:
            raise MayaPlaybackHostError("Maya time unit changed after Playback Host capture")

    @staticmethod
    def _unit_label(value: Any) -> str:
        """Maya unit enumをimmutableな短い文字列へ変換する。"""

        if value is None:
            return "ui"
        if isinstance(value, str):
            return value
        return str(value)


def _finite_number(value: object, field_name: str) -> None:
    """boolでない有限数を検証する。"""

    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise MayaPlaybackHostError(f"{field_name} must be a finite number")


def _positive_number(value: object, field_name: str) -> None:
    """正の有限数を検証する。"""

    _finite_number(value, field_name)
    if value <= 0:  # type: ignore[operator]
        raise MayaPlaybackHostError(f"{field_name} must be positive")


def _member_value(instance: Any, name: str, default: Any = None) -> Any:
    """method/propertyどちらのMaya APIでも値を取得する。"""

    value = getattr(instance, name, default)
    if callable(value):
        return value()
    return value


def _time_value(value: Any) -> float | int:
    """MTimeと数値の両方から時刻値を取得する。"""

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        _finite_number(value, "time")
        return value
    member = getattr(value, "value", None)
    if callable(member):
        member = member()
    _finite_number(member, "time")
    return member


def _default_direction_query() -> bool | None:
    """Mayaの再生方向をqueryする。Maya外ではNoneを返す。"""

    if _MAYA_CMDS is None:
        return None
    return _MAYA_CMDS.play(query=True, forward=True)


def _default_time_unit_label_query() -> str:
    """Maya commandから現在time unit labelを取得する。"""

    if _MAYA_CMDS is None:
        raise MayaPlaybackHostUnavailableError("Maya cmds is unavailable")
    current_unit = getattr(_MAYA_CMDS, "currentUnit", None)
    if not callable(current_unit):
        raise MayaPlaybackHostUnavailableError("maya.cmds.currentUnit is unavailable")
    value = current_unit(q=True, time=True)
    if not isinstance(value, str) or not value.strip():
        raise MayaPlaybackHostError("current Maya time unit label is invalid")
    return value


def _none_direction_query() -> None:
    """注入API利用時の方向query。"""

    return None


__all__ = (
    "CallbackErrorStatus",
    "MAYA_PLAYBACK_EVENTS",
    "MayaPlaybackHost",
    "MayaPlaybackHostError",
    "MayaPlaybackHostUnavailableError",
)
