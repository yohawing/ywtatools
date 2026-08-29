"""Blenderの再生状態をYWTA LinkのHost型へ投影する薄いbridge。"""

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
    import bpy as _BPY
except ImportError:  # Blender外の標準Pythonテストでは依存注入を使う。
    _BPY = None


class BlenderPlaybackHostError(RuntimeError):
    """Blender Playback Host bridgeの設定または状態が不正である。"""


class BlenderPlaybackHostUnavailableError(BlenderPlaybackHostError):
    """Blender Python APIまたは必要なcallbackが利用できない。"""


@dataclass(frozen=True)
class CallbackErrorStatus:
    """Blender callback内で隔離した最後の例外情報。"""

    callback: str
    exception_type: str
    message: str
    count: int


BLENDER_PLAYBACK_HANDLERS = (
    "animation_playback_pre",
    "animation_playback_post",
    "frame_change_post",
)


class BlenderPlaybackHost:
    """Blender playback callbackの登録とMain Thread applyを担当するbridge。

    ``bpy_module``、scene/screen provider、playback controlを注入すればBlender外で
    callbackとapplyの境界を検証できる。Bridge自身はnetwork送信を行わず、local変更だけを
    ``on_change``へ通知する。Blenderは再生方向のqueryを安定して公開しないため、原則として
    frame deltaが確定するまでplay startを保留する。
    """

    def __init__(
        self,
        on_change: Callable[[PlaybackHostEvent], None],
        *,
        bpy_module: Any = None,
        scene_provider: Callable[[], Any] | None = None,
        screen_provider: Callable[[], Any] | None = None,
        playback_control: Callable[[str, str | None], None] | None = None,
        direction_query: Callable[[], Any] | None = None,
        job_running_query: Callable[[], Any] | None = None,
        speed_query: Callable[[Any], Any] | None = None,
        speed_apply: Callable[[Any, float], None] | None = None,
        loop_mode_query: Callable[[Any], Any] | None = None,
        loop_mode_apply: Callable[[Any, str], None] | None = None,
        timebase_validator: Callable[[Any], Any] | None = None,
        timer_interval: float = 0.1,
    ) -> None:
        """Blender API依存を解決し、所有Main Threadを記録する。"""

        if not callable(on_change):
            raise BlenderPlaybackHostError("on_change must be callable")
        for name, value in (
            ("scene_provider", scene_provider),
            ("screen_provider", screen_provider),
            ("playback_control", playback_control),
            ("direction_query", direction_query),
            ("job_running_query", job_running_query),
            ("speed_query", speed_query),
            ("speed_apply", speed_apply),
            ("loop_mode_query", loop_mode_query),
            ("loop_mode_apply", loop_mode_apply),
            ("timebase_validator", timebase_validator),
        ):
            if value is not None and not callable(value):
                raise BlenderPlaybackHostError(f"{name} must be callable")
        if speed_apply is not None and speed_query is None:
            raise BlenderPlaybackHostError("speed_apply requires speed_query")
        if loop_mode_apply is not None and loop_mode_query is None:
            raise BlenderPlaybackHostError("loop_mode_apply requires loop_mode_query")
        _positive_number(timer_interval, "timer_interval")

        self._bpy = _BPY if bpy_module is None else bpy_module
        if self._bpy is None:
            raise BlenderPlaybackHostUnavailableError("Blender Python API is unavailable; inject bpy_module for tests")
        self._scene_provider = scene_provider or self._default_scene
        self._screen_provider = screen_provider or self._default_screen
        self._playback_control = playback_control or self._default_playback_control
        self._direction_query = direction_query
        self._job_running_query = job_running_query or self._default_job_running_query
        self._speed_query = speed_query
        self._speed_apply = speed_apply
        self._loop_mode_query = loop_mode_query
        self._loop_mode_apply = loop_mode_apply
        self._timebase_validator = timebase_validator
        self._timer_interval = float(timer_interval)
        self._on_change = on_change

        self._owner_thread_id = threading.get_ident()
        self._registered = False
        self._timer_registered = False
        self._applying = False
        self._playing: bool | None = None
        self._pending_start = False
        self._last_frame: float | int | None = None
        self._last_direction = "forward"
        self._last_dynamic: tuple[Any, ...] | None = None
        self._suppress_seek_position: float | int | None = None
        self._last_apply_approximated_fields: tuple[str, ...] = ()
        self._last_error: CallbackErrorStatus | None = None
        self._error_count = 0
        self._handler_callbacks = self._make_handler_callbacks()
        self._timer_callback_wrapper = self._make_persistent_callback(
            "timer",
            self._timer_callback,
        )

    @property
    def registered(self) -> bool:
        """callbackとtimerが登録済みかを返す。"""

        return self._registered

    @property
    def last_error(self) -> CallbackErrorStatus | None:
        """隔離された最後のcallback例外を返す。"""

        return self._last_error

    @property
    def last_apply_approximated_fields(self) -> tuple[str, ...]:
        """直近のremote applyで近似されたFieldを返す。"""

        return self._last_apply_approximated_fields

    def register(self) -> bool:
        """Blender handlersとMain Thread timerを一度だけ登録する。"""

        self._assert_owner_thread("register")
        if self._registered:
            return False
        handlers = self._handler_lists()
        timers = self._timers()
        callbacks = self._callback_map()
        try:
            for name, callback in callbacks.items():
                self._append_handler_once(handlers[name], callback)

            register_timer = getattr(timers, "register", None)
            if not callable(register_timer):
                raise BlenderPlaybackHostUnavailableError("bpy.app.timers.register is unavailable")
            register_timer(
                self._timer_callback_wrapper,
                first_interval=self._timer_interval,
                persistent=True,
            )
            self._timer_registered = True

            scene = self._scene()
            self._validate_timebase(scene)
            self._playing = self._read_playing()
            self._last_frame = self._read_frame(scene)
            self._last_dynamic = self._dynamic_signature(scene)
        except BaseException as exc:
            try:
                self._remove_callbacks_safely(handlers, timers)
            except BaseException as cleanup_error:
                self._registered = bool(self._remaining_callbacks(handlers)) or self._timer_registered
                raise BlenderPlaybackHostError(
                    "Blender playback callback registration failed; callback cleanup failed"
                ) from cleanup_error
            self._registered = False
            raise BlenderPlaybackHostError("Blender playback callback registration failed") from exc

        self._registered = True
        return True

    def unregister(self) -> bool:
        """登録したhandlerとtimerを個別解除する。失敗した対象は台帳へ残す。"""

        self._assert_owner_thread("unregister")
        handlers = self._handler_lists()
        timers = self._timers()
        if not self._remaining_callbacks(handlers) and not self._timer_registered:
            self._registered = False
            return False
        try:
            self._remove_callbacks_safely(handlers, timers)
        except BaseException as exc:
            self._registered = bool(self._remaining_callbacks(handlers)) or self._timer_registered
            raise BlenderPlaybackHostError("Blender playback callback removal failed") from exc

        self._registered = False
        self._playing = None
        self._pending_start = False
        self._last_frame = None
        self._last_dynamic = None
        return True

    close = unregister

    def tick(self) -> None:
        """Main Threadでrange/speed/loop差分を検出し、必要なeventを通知する。"""

        self._assert_owner_thread("tick")
        if not self._registered:
            return
        scene = self._scene()
        self._validate_timebase(scene)
        self._maybe_start(scene)
        current_dynamic = self._dynamic_signature(scene)
        previous_dynamic = self._last_dynamic
        self._last_dynamic = current_dynamic
        if previous_dynamic is None or previous_dynamic == current_dynamic or self._applying:
            return
        old_range, old_speed, old_loop = previous_dynamic
        new_range, new_speed, new_loop = current_dynamic
        if old_range != new_range:
            self._emit(PlaybackHostEventKind.RANGE_CHANGED, scene)
        if old_speed != new_speed:
            self._emit(PlaybackHostEventKind.SPEED_CHANGED, scene)
        if old_loop != new_loop:
            self._emit(PlaybackHostEventKind.MODE_CHANGED, scene)

    def apply(self, snapshot: PlaybackHostSnapshot) -> None:
        """Remote snapshotをBlender Main Threadへ適用する。

        Blenderのinclusiveな``frame_end``へはwireの``end_exclusive - frame_step``を
        設定する。play/stopはcontext依存のoperatorを直接呼ばず、注入可能なcontrol portを
        介して行う。loop意図は標準Blender sceneに共通setterがないため、setter未注入時は
        明示的に近似として記録する。
        """

        self._assert_owner_thread("apply")
        if not isinstance(snapshot, PlaybackHostSnapshot):
            raise BlenderPlaybackHostError("snapshot must be a PlaybackHostSnapshot")
        scene = self._scene()
        self._validate_timebase(scene)
        frame_step = self._read_frame_step(scene)
        start, end_inclusive = self.wire_range_to_blender(snapshot.playback_range, frame_step=frame_step)
        current_playing = self._read_playing()
        range_start_name, range_end_name = self._range_property_names(scene)
        approximated: list[str] = []

        self._applying = True
        try:
            if current_playing:
                self._call_playback_control("stop", None)
            self._set_scene_value(scene, range_start_name, start)
            self._set_scene_value(scene, range_end_name, end_inclusive)
            if self._speed_apply is None:
                approximated.append("speed")
            else:
                self._apply_speed(scene, snapshot.speed)
            if self._loop_mode_apply is None:
                approximated.append("loop_mode")
            else:
                self._loop_mode_apply(scene, snapshot.loop_mode)
            self._set_scene_frame(scene, snapshot.position)
            if snapshot.state == "playing":
                self._call_playback_control("play", snapshot.direction)
            self._last_direction = snapshot.direction
            self._playing = snapshot.state == "playing"
            self._pending_start = False
            self._last_frame = snapshot.position
            self._last_dynamic = self._dynamic_signature(scene)
            self._suppress_seek_position = snapshot.position
        finally:
            self._applying = False
        self._last_apply_approximated_fields = tuple(approximated)

    apply_snapshot = apply

    def snapshot(self) -> PlaybackHostSnapshot:
        """現在のBlender playback状態をMain Thread上で取得する。"""

        self._assert_owner_thread("snapshot")
        return self._read_snapshot()

    @staticmethod
    def blender_range_to_wire(
        start: float | int,
        end_inclusive: float | int,
        *,
        frame_step: float | int = 1,
    ) -> PlaybackHostRange:
        """Blender inclusive rangeをwireの半開rangeへ変換する。"""

        frame_step = _integer_boundary(frame_step, "frame_step")
        start = _integer_boundary(start, "start")
        end_inclusive = _integer_boundary(end_inclusive, "end_inclusive")
        return PlaybackHostRange(start, end_inclusive + frame_step)

    @staticmethod
    def wire_range_to_blender(
        playback_range: PlaybackHostRange | Mapping[str, Any],
        *,
        frame_step: float | int = 1,
    ) -> tuple[float | int, float | int]:
        """wire半開rangeをBlender inclusive rangeへ戻す。"""

        frame_step = _integer_boundary(frame_step, "frame_step")
        if not isinstance(playback_range, PlaybackHostRange):
            try:
                playback_range = PlaybackHostRange(
                    playback_range["start"],
                    playback_range["end_exclusive"],
                )
            except (KeyError, TypeError) as exc:
                raise BlenderPlaybackHostError("playback_range must contain start and end_exclusive") from exc
        start = _integer_boundary(playback_range.start, "range start")
        end_exclusive = _integer_boundary(playback_range.end_exclusive, "range end_exclusive")
        end_inclusive = end_exclusive - frame_step
        if start > end_inclusive:
            raise BlenderPlaybackHostError("wire playback range is shorter than frame_step")
        return start, end_inclusive

    def _animation_playback_pre_callback(self, scene: Any = None, *_args: Any, **_kwargs: Any) -> None:
        """再生開始前に方向をqueryし、未確定ならframe deltaを待つ。"""

        self._invoke_callback("animation_playback_pre", lambda: self._handle_playback_pre(scene))

    def _animation_playback_post_callback(self, scene: Any = None, *_args: Any, **_kwargs: Any) -> None:
        """再生停止後の最終位置を含むstop eventを通知する。"""

        self._invoke_callback("animation_playback_post", lambda: self._handle_playback_post(scene))

    def _frame_change_post_callback(self, scene: Any = None, *_args: Any, **_kwargs: Any) -> None:
        """再生中の毎frameを抑止し、paused seekだけを通知する。"""

        self._invoke_callback("frame_change_post", lambda: self._handle_frame_change(scene))

    def _handle_playback_pre(self, scene: Any = None) -> None:
        """再生開始edgeを方向確定まで保留する。"""

        self._assert_owner_thread("animation_playback_pre")
        scene = self._scene(scene)
        self._validate_timebase(scene)
        if self._applying or self._playing is True:
            return
        self._pending_start = True
        self._last_frame = self._read_frame(scene)
        direction = self._query_direction()
        if direction is not None:
            self._start_playback(direction, scene)

    def _handle_playback_post(self, scene: Any = None) -> None:
        """再生停止edgeを一度だけ通知する。"""

        self._assert_owner_thread("animation_playback_post")
        scene = self._scene(scene)
        self._validate_timebase(scene)
        current = self._read_frame(scene)
        was_playing = self._playing is True
        self._pending_start = False
        self._playing = False
        self._last_frame = current
        self._suppress_seek_position = current
        if was_playing and not self._applying:
            self._emit(PlaybackHostEventKind.PLAY_STOPPED, scene)

    def _handle_frame_change(self, scene: Any = None) -> None:
        """frame deltaから方向を確定し、paused seekを通知する。"""

        self._assert_owner_thread("frame_change_post")
        scene = self._scene(scene)
        self._validate_timebase(scene)
        if self._render_state() is not False:
            # Render中またはjob状態不明のframe callbackはseekへ昇格しない。
            self._last_frame = self._read_frame(scene)
            return
        current = self._read_frame(scene)
        previous = self._last_frame
        self._last_frame = current
        is_playing = self._read_playing()
        if is_playing and (self._pending_start or self._playing is not True):
            direction = self._direction_from_delta(previous, current, scene) or self._query_direction()
            if direction is not None:
                self._start_playback(direction, scene)
        if self._pending_start:
            return
        if self._applying or is_playing or self._playing is True:
            return
        if self._suppress_seek_position is not None:
            if self._suppress_seek_position == current:
                self._suppress_seek_position = None
                return
            self._suppress_seek_position = None
        if previous != current:
            self._emit(PlaybackHostEventKind.PAUSED_SEEK, scene)

    def _maybe_start(self, scene: Any) -> None:
        """timer tickでも開始方向を確定できる場合にstart eventを通知する。"""

        if self._applying or not self._pending_start:
            return
        current = self._read_frame(scene)
        previous = self._last_frame
        self._last_frame = current
        direction = self._direction_from_delta(previous, current, scene) or self._query_direction()
        if self._read_playing() and direction is not None:
            self._start_playback(direction, scene)

    def _start_playback(self, direction: str, scene: Any) -> None:
        """確定した方向で一度だけplay start eventを通知する。"""

        if self._playing is True or self._applying:
            return
        self._last_direction = direction
        self._playing = True
        self._pending_start = False
        self._emit(PlaybackHostEventKind.PLAY_STARTED, scene)

    def _emit(self, kind: PlaybackHostEventKind, scene: Any = None) -> None:
        """current snapshotをimmutable eventとして安全に通知する。"""

        if self._applying:
            return
        try:
            scene = self._scene(scene)
            self._validate_timebase(scene)
            event = PlaybackHostEvent(kind=kind, snapshot=self._read_snapshot(scene))
            self._on_change(event)
        except BaseException as exc:
            self._record_error(kind.value, exc)

    def _invoke_callback(self, callback_name: str, callback: Callable[[], None]) -> None:
        """Blender event loopへ例外を漏らさずcallbackを実行する。"""

        try:
            callback()
        except BaseException as exc:
            self._record_error(callback_name, exc)

    def _read_snapshot(self, scene: Any = None) -> PlaybackHostSnapshot:
        """Blender sceneからDCC非依存のsnapshotを作る。"""

        scene = self._scene(scene)
        self._validate_timebase(scene)
        current = self._read_frame(scene)
        start, end = self._effective_range(scene)
        frame_step = self._read_frame_step(scene)
        speed, speed_approx = self._read_speed(scene)
        loop_mode, loop_approx = self._read_loop_mode(scene)
        is_playing = self._playing is True or self._read_playing()
        approximated = []
        if speed_approx:
            approximated.append("speed")
        if loop_approx:
            approximated.append("loop_mode")
        return PlaybackHostSnapshot(
            state="playing" if is_playing else "paused",
            position=current,
            playback_range=self.blender_range_to_wire(start, end, frame_step=frame_step),
            speed=speed,
            direction=self._last_direction,
            loop_mode=loop_mode,
            time_unit="frames",
            change_id=uuid.uuid4().hex,
            approximated_fields=tuple(approximated),
        )

    def _dynamic_signature(self, scene: Any) -> tuple[Any, ...]:
        """timerで比較するrange/speed/loopのimmutableなsnapshotを返す。"""

        start, end = self._effective_range(scene)
        frame_step = self._read_frame_step(scene)
        speed, _ = self._read_speed(scene)
        loop_mode, _ = self._read_loop_mode(scene)
        return ((start, end + frame_step), speed, loop_mode)

    def _read_speed(self, scene: Any) -> tuple[float, bool]:
        """任意providerからspeedを取得し、未対応Hostは1倍へ明示近似する。"""

        if self._speed_query is not None:
            value = self._speed_query(scene)
            _positive_number(value, "speed")
            return float(value), False
        # Blenderのfps/fps_baseはscene timebaseであり、再生倍率ではない。
        return 1.0, True

    def _read_loop_mode(self, scene: Any) -> tuple[str, bool]:
        """loop providerがなければBlender標準のonceへ明示近似する。"""

        if self._loop_mode_query is None:
            return "once", True
        value = self._loop_mode_query(scene)
        if value not in ("once", "loop", "ping-pong"):
            raise BlenderPlaybackHostError("loop_mode_query returned an unsupported value")
        return value, False

    def _apply_speed(self, scene: Any, speed: float) -> None:
        """注入されたspeed providerへremote speedを安全に適用する。"""

        _positive_number(speed, "speed")
        if self._speed_apply is not None:
            self._speed_apply(scene, float(speed))
            return
        # speed_apply未注入時はcallerが明示approximationを記録し、timebaseを変更しない。

    def _read_frame_step(self, scene: Any) -> float | int:
        """Blenderのpositive frame_stepを取得する。"""

        return _integer_boundary(getattr(scene, "frame_step", 1), "frame_step", positive=True)

    def _effective_range(self, scene: Any) -> tuple[int, int]:
        """preview range設定を考慮したinclusiveなRNA rangeを取得する。"""

        start_name, end_name = self._range_property_names(scene)
        start = _integer_boundary(getattr(scene, start_name), start_name)
        end = _integer_boundary(getattr(scene, end_name), end_name)
        if start > end:
            raise BlenderPlaybackHostError("Blender playback range start must not exceed end")
        return start, end

    @staticmethod
    def _range_property_names(scene: Any) -> tuple[str, str]:
        """preview range有効時だけpreview RNAを選択する。"""

        if bool(getattr(scene, "use_preview_range", False)):
            return "frame_preview_start", "frame_preview_end"
        return "frame_start", "frame_end"

    def _read_frame(self, scene: Any) -> float | int:
        """scene.frame_currentを有限な数値として取得する。"""

        frame = _finite_value(getattr(scene, "frame_current"), "frame_current")
        subframe = _finite_value(getattr(scene, "frame_subframe", 0.0), "frame_subframe")
        value = float(frame) + float(subframe)
        if subframe == 0:
            return frame
        return value

    @staticmethod
    def _set_scene_frame(scene: Any, position: float | int) -> None:
        """scene.frame_setへframeとsubframeを分離して位置を適用する。"""

        _finite_number(position, "position")
        frame_set = getattr(scene, "frame_set", None)
        if not callable(frame_set):
            raise BlenderPlaybackHostUnavailableError("scene.frame_set is unavailable")
        frame = math.floor(float(position))
        subframe = float(position) - frame
        try:
            frame_set(frame, subframe=subframe)
        except BaseException as exc:
            raise BlenderPlaybackHostError("cannot set Blender frame position") from exc

    def _read_playing(self) -> bool:
        """screen.is_animation_playingをcontext依存境界から取得する。"""

        screen = self._screen()
        value = getattr(screen, "is_animation_playing", None)
        if callable(value):
            value = value()
        if not isinstance(value, bool):
            raise BlenderPlaybackHostUnavailableError("screen.is_animation_playing is unavailable")
        return value

    def _render_state(self) -> bool | None:
        """Blender render job状態を取得し、不明ならNoneを返す。"""

        try:
            value = self._job_running_query()
        except BaseException as exc:
            self._record_error("job_running_query", exc)
            return None
        if isinstance(value, bool):
            return value
        return None

    def _default_job_running_query(self) -> bool | None:
        """bpy.app.is_job_runningでRENDER状態を取得する。"""

        query = getattr(getattr(self._bpy, "app", None), "is_job_running", None)
        if not callable(query):
            return None
        value = query("RENDER")
        return value if isinstance(value, bool) else None

    def _query_direction(self) -> str | None:
        """注入されたqueryが正しい方向を返した場合だけ採用する。"""

        if self._direction_query is None:
            return None
        try:
            value = self._direction_query()
        except BaseException as exc:
            self._record_error("direction_query", exc)
            return None
        if isinstance(value, bool):
            value = "forward" if value else "reverse"
        if value in ("forward", "reverse"):
            self._last_direction = value
            return value
        return None

    def _direction_from_delta(
        self,
        previous: float | int | None,
        current: float | int,
        scene: Any,
    ) -> str | None:
        """frame deltaから方向を返し、range端のwrapは次deltaまで保留する。"""

        if previous is None or current == previous:
            return None
        range_start, range_end = self._effective_range(scene)
        if previous >= range_end and current <= range_start:
            return None
        if previous <= range_start and current >= range_end:
            return None
        return "forward" if current > previous else "reverse"

    def _call_playback_control(self, action: str, direction: str | None) -> None:
        """context依存のplay/stop portを呼び出す。"""

        try:
            self._playback_control(action, direction)
        except BlenderPlaybackHostError:
            raise
        except BaseException as exc:
            raise BlenderPlaybackHostError(f"playback control {action} failed") from exc

    def _default_playback_control(self, action: str, direction: str | None) -> None:
        """Blender operatorを最小限のcontext依存境界として呼び出す。"""

        screen_ops = getattr(getattr(self._bpy, "ops", None), "screen", None)
        if action == "stop":
            operation = getattr(screen_ops, "animation_cancel", None)
            if not callable(operation):
                raise BlenderPlaybackHostUnavailableError("bpy.ops.screen.animation_cancel is unavailable")
            operation(restore_frame=False)
            return
        if action == "play":
            operation = getattr(screen_ops, "animation_play", None)
            if not callable(operation):
                raise BlenderPlaybackHostUnavailableError("bpy.ops.screen.animation_play is unavailable")
            operation(reverse=direction == "reverse")
            return
        raise BlenderPlaybackHostError(f"unsupported playback control action: {action}")

    def _handler_lists(self) -> dict[str, Any]:
        """Blender handler listを取得する。"""

        handlers = getattr(getattr(self._bpy, "app", None), "handlers", None)
        if handlers is None:
            raise BlenderPlaybackHostUnavailableError("bpy.app.handlers is unavailable")
        result = {}
        for name in BLENDER_PLAYBACK_HANDLERS:
            value = getattr(handlers, name, None)
            if value is None or not hasattr(value, "append") or not hasattr(value, "remove"):
                raise BlenderPlaybackHostUnavailableError(f"bpy.app.handlers.{name} is unavailable")
            result[name] = value
        return result

    def _timers(self) -> Any:
        """Blender timer APIを取得する。"""

        timers = getattr(getattr(self._bpy, "app", None), "timers", None)
        if timers is None:
            raise BlenderPlaybackHostUnavailableError("bpy.app.timers is unavailable")
        return timers

    def _callback_map(self) -> dict[str, Callable[..., None]]:
        """handler名とbridge callbackの対応を返す。"""

        return self._handler_callbacks

    def _make_handler_callbacks(self) -> dict[str, Callable[..., None]]:
        """handler callbackのwrapperを一度だけ生成して保持する。"""

        return {
            "animation_playback_pre": self._make_persistent_callback(
                "animation_playback_pre",
                self._animation_playback_pre_callback,
            ),
            "animation_playback_post": self._make_persistent_callback(
                "animation_playback_post",
                self._animation_playback_post_callback,
            ),
            "frame_change_post": self._make_persistent_callback(
                "frame_change_post",
                self._frame_change_post_callback,
            ),
        }

    def _make_persistent_callback(
        self,
        callback_name: str,
        callback: Callable[..., None],
    ) -> Callable[..., None]:
        """可変引数を受けるstable wrapperへpersistent属性を適用する。"""

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return callback(*args, **kwargs)

        wrapper.__name__ = f"_ywta_link_{callback_name}"
        handlers = getattr(getattr(self._bpy, "app", None), "handlers", None)
        persistent = getattr(handlers, "persistent", None)
        if callable(persistent):
            decorated = persistent(wrapper)
            if not callable(decorated):
                raise BlenderPlaybackHostUnavailableError("bpy.app.handlers.persistent returned a non-callable wrapper")
            return decorated
        return wrapper

    @staticmethod
    def _append_handler_once(handler_list: Any, callback: Callable[..., None]) -> None:
        """同じcallbackを重複登録せず、既存重複も一つへ縮約する。"""

        found = False
        for existing in tuple(handler_list):
            if existing is not callback:
                continue
            if found:
                handler_list.remove(existing)
            else:
                found = True
        if not found:
            handler_list.append(callback)

    def _remove_callbacks_safely(self, handlers: dict[str, Any], timers: Any) -> None:
        """実際に残ったhandlerを観測し、timerと各handlerを個別解除する。"""

        failures: list[BaseException] = []
        for name, callback in self._callback_map().items():
            handler_list = handlers[name]
            for existing in tuple(handler_list):
                if existing is not callback:
                    continue
                try:
                    handler_list.remove(existing)
                except BaseException as exc:
                    failures.append(exc)
        if self._timer_registered:
            unregister_timer = getattr(timers, "unregister", None)
            if not callable(unregister_timer):
                failures.append(BlenderPlaybackHostUnavailableError("bpy.app.timers.unregister is unavailable"))
            else:
                try:
                    unregister_timer(self._timer_callback_wrapper)
                except BaseException as exc:
                    failures.append(exc)
                else:
                    self._timer_registered = False
        if failures:
            raise failures[0]

    def _remaining_callbacks(self, handlers: dict[str, Any]) -> bool:
        """登録callbackがhandler listに残っているかを実測する。"""

        callbacks = self._callback_map()
        return any(any(existing is callbacks[name] for existing in handlers[name]) for name in callbacks)

    def _scene(self, scene: Any = None) -> Any:
        """callback引数または注入providerからsceneを取得する。"""

        value = scene if scene is not None else self._scene_provider()
        if value is None:
            raise BlenderPlaybackHostUnavailableError("Blender scene is unavailable")
        return value

    def _validate_timebase(self, scene: Any) -> None:
        """注入されたtimebase validatorで対象sceneを直前検証する。"""

        if self._timebase_validator is None:
            return
        try:
            result = self._timebase_validator(scene)
        except BlenderPlaybackHostError:
            raise
        except BaseException as exc:
            raise BlenderPlaybackHostError("Blender scene timebase validation failed") from exc
        if result is False:
            raise BlenderPlaybackHostError("Blender scene timebase validator rejected the scene")

    def _screen(self) -> Any:
        """注入providerからscreenを取得する。"""

        value = self._screen_provider()
        if value is None:
            raise BlenderPlaybackHostUnavailableError("Blender screen is unavailable")
        return value

    def _default_scene(self) -> Any:
        """現在のBlender context sceneを返す。"""

        return self._bpy.context.scene

    def _default_screen(self) -> Any:
        """現在のBlender context screenを返す。"""

        return self._bpy.context.screen

    @staticmethod
    def _set_scene_value(instance: Any, name: str, value: Any) -> None:
        """DCC property setterの失敗を明示的なbridge errorへ変換する。"""

        try:
            setattr(instance, name, value)
        except BaseException as exc:
            raise BlenderPlaybackHostError(f"cannot set Blender property {name}") from exc

    def _timer_callback(self) -> float | None:
        """Blender timerから呼ばれ、例外をstatusへ隔離して再登録間隔を返す。"""

        if not self._registered:
            # BlenderはNoneを返したtimer callbackを台帳から除去する。
            self._timer_registered = False
            return None
        try:
            self.tick()
        except BaseException as exc:
            self._record_error("timer", exc)
        return self._timer_interval if self._registered else None

    def _assert_owner_thread(self, operation: str) -> None:
        """Blender Main Thread以外からの操作を拒否する。"""

        if threading.get_ident() != self._owner_thread_id:
            raise BlenderPlaybackHostError(f"{operation} must run on the Blender Main Thread")

    def _record_error(self, callback_name: str, error: BaseException) -> None:
        """例外本体を保持せず、観測可能な軽量statusを更新する。"""

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


def _finite_number(value: object, field_name: str) -> None:
    """boolでない有限数を検証する。"""

    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise BlenderPlaybackHostError(f"{field_name} must be a finite number")


def _finite_value(value: object, field_name: str) -> float | int:
    """有限数を検証して元の数値型を返す。"""

    _finite_number(value, field_name)
    return value  # type: ignore[return-value]


def _positive_number(value: object, field_name: str) -> float | int:
    """正の有限数を検証して元の数値型を返す。"""

    _finite_number(value, field_name)
    if value <= 0:  # type: ignore[operator]
        raise BlenderPlaybackHostError(f"{field_name} must be positive")
    return value  # type: ignore[return-value]


def _integer_boundary(value: object, field_name: str, *, positive: bool = False) -> int:
    """Blenderのinteger RNA boundaryを暗黙coerceせず検証する。"""

    _finite_number(value, field_name)
    numeric = float(value)
    if not numeric.is_integer():
        raise BlenderPlaybackHostError(f"{field_name} must be an integer boundary")
    integer = int(numeric)
    if positive and integer <= 0:
        raise BlenderPlaybackHostError(f"{field_name} must be positive")
    return integer


__all__ = (
    "BLENDER_PLAYBACK_HANDLERS",
    "BlenderPlaybackHost",
    "BlenderPlaybackHostError",
    "BlenderPlaybackHostUnavailableError",
    "CallbackErrorStatus",
)
