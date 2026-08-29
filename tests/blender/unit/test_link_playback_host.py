"""Blender Playback Host bridgeのcallback/apply境界を検証する。"""

from __future__ import annotations

import threading
import types
import unittest
import importlib.util
from pathlib import Path
import sys
from unittest import mock

_MODULE_SPEC = importlib.util.spec_from_file_location(
    "ywtatools_addon.link_playback",
    Path(__file__).parents[3] / "blender" / "addons" / "ywtatools_addon" / "link_playback.py",
)
if _MODULE_SPEC is None or _MODULE_SPEC.loader is None:
    raise ImportError("cannot load Blender Playback Host module")
_MODULE = importlib.util.module_from_spec(_MODULE_SPEC)
sys.modules[_MODULE_SPEC.name] = _MODULE
_MODULE_SPEC.loader.exec_module(_MODULE)

BLENDER_PLAYBACK_HANDLERS = _MODULE.BLENDER_PLAYBACK_HANDLERS
BlenderPlaybackHost = _MODULE.BlenderPlaybackHost
BlenderPlaybackHostError = _MODULE.BlenderPlaybackHostError
BlenderPlaybackHostUnavailableError = _MODULE.BlenderPlaybackHostUnavailableError

from ywta_link.playback_host import PlaybackHostEventKind, PlaybackHostRange, PlaybackHostSnapshot
from ywta_link import RationalRate


class _Handlers:
    """Blender handler listの最小fake。"""

    def __init__(self):
        for name in BLENDER_PLAYBACK_HANDLERS:
            setattr(self, name, [])

    @staticmethod
    def persistent(callback):
        """Blender persistent decoratorの最小fake。"""

        callback.persistent = True
        return callback

    def simulate_file_load(self):
        """非persistent callbackだけをfile loadで除去するfake。"""

        for name in BLENDER_PLAYBACK_HANDLERS:
            handler = getattr(self, name)
            handler[:] = [callback for callback in handler if getattr(callback, "persistent", False)]


class _Timers:
    """Blender timer APIの最小fake。"""

    def __init__(self):
        self.callbacks = []
        self.fail_unregister = False

    def register(self, callback, first_interval, persistent=False):
        self.callbacks.append((callback, first_interval, persistent))

    def unregister(self, callback):
        if self.fail_unregister:
            raise RuntimeError("timer removal failed")
        self.callbacks = [entry for entry in self.callbacks if entry[0] != callback]


class _Scene:
    """Playbackに必要なBlender scene/render属性のfake。"""

    def __init__(self):
        self.frame_current = 1
        self.frame_start = 1
        self.frame_end = 24
        self.frame_step = 1
        self.frame_subframe = 0.0
        self.use_preview_range = False
        self.frame_preview_start = 1
        self.frame_preview_end = 24
        self.render = types.SimpleNamespace(fps=24, fps_base=1.0)

    def frame_set(self, frame, subframe=0.0):
        self.frame_current = frame
        self.frame_subframe = subframe


class _Screen:
    """screen.is_animation_playingのfake。"""

    def __init__(self):
        self.is_animation_playing = False


class _Bpy:
    """注入用の最小bpy module fake。"""

    def __init__(self, scene, screen):
        self.context = types.SimpleNamespace(scene=scene, screen=screen)
        self.app = types.SimpleNamespace(handlers=_Handlers(), timers=_Timers())
        self.app.is_job_running = lambda _name: False
        self.ops = types.SimpleNamespace(screen=types.SimpleNamespace())


def _snapshot(**changes):
    """テスト用remote snapshotを作る。"""

    value = {
        "state": "paused",
        "position": 12.0,
        "playback_range": PlaybackHostRange(1.0, 25.0),
        "speed": 2.0,
        "direction": "reverse",
        "loop_mode": "loop",
        "time_unit": "frames",
        "change_id": "remote-001",
    }
    value.update(changes)
    return PlaybackHostSnapshot(**value)


class BlenderPlaybackHostTests(unittest.TestCase):
    """Blender APIを使わないPlayback bridgeの契約テスト。"""

    def setUp(self):
        self.scene = _Scene()
        self.screen = _Screen()
        self.bpy = _Bpy(self.scene, self.screen)
        self.events = []
        self.controls = []
        self.host = BlenderPlaybackHost(
            self.events.append,
            bpy_module=self.bpy,
            playback_control=self._control,
        )

    def _control(self, action, direction):
        self.controls.append((action, direction))
        self.screen.is_animation_playing = action == "play"

    def test_import_dependency_is_reported_at_constructor(self):
        with mock.patch.object(_MODULE, "_BPY", None):
            with self.assertRaises(BlenderPlaybackHostUnavailableError):
                BlenderPlaybackHost(lambda _event: None, bpy_module=None)

    def test_snapshot_returns_typed_current_state_without_registration(self):
        snapshot = self.host.snapshot()
        self.assertIs(type(snapshot), PlaybackHostSnapshot)
        self.assertEqual(1, snapshot.position)
        self.assertEqual(PlaybackHostRange(1, 25), snapshot.playback_range)

    def test_timebase_validator_rejects_drift_before_snapshot_and_apply(self):
        host = BlenderPlaybackHost(
            self.events.append,
            bpy_module=self.bpy,
            playback_control=self._control,
            timebase_validator=lambda scene: RationalRate(scene.render.fps, 1) == RationalRate(24, 1),
        )
        self.assertEqual(1, host.snapshot().position)

        self.scene.render.fps = 30
        with self.assertRaises(BlenderPlaybackHostError):
            host.snapshot()
        with self.assertRaises(BlenderPlaybackHostError):
            host.apply(_snapshot())

    def test_timebase_validator_failure_is_isolated_in_callback(self):
        host = BlenderPlaybackHost(
            self.events.append,
            bpy_module=self.bpy,
            timebase_validator=lambda _scene: False,
        )
        host._timer_registered = True
        host._registered = True

        result = host._timer_callback()

        self.assertEqual(result, host._timer_interval)
        self.assertIsNotNone(host.last_error)
        self.assertEqual(host.last_error.exception_type, "BlenderPlaybackHostError")

    def test_invalid_rate_callbacks_leave_state_unchanged_and_recover(self):
        expected_rate = RationalRate(24, 1)

        def validate_timebase(scene):
            return RationalRate(scene.render.fps, 1) == expected_rate

        host = BlenderPlaybackHost(
            self.events.append,
            bpy_module=self.bpy,
            playback_control=self._control,
            timebase_validator=validate_timebase,
        )
        host.register()
        initial_state = (
            host._pending_start,
            host._playing,
            host._last_frame,
            host._suppress_seek_position,
            host._last_direction,
            host._last_dynamic,
        )

        self.scene.render.fps = 30
        host._animation_playback_pre_callback(self.scene)
        host._animation_playback_post_callback(self.scene)
        host._frame_change_post_callback(self.scene)
        self.assertEqual(
            initial_state,
            (
                host._pending_start,
                host._playing,
                host._last_frame,
                host._suppress_seek_position,
                host._last_direction,
                host._last_dynamic,
            ),
        )
        self.assertEqual([], self.events)

        self.scene.render.fps = 24
        self.screen.is_animation_playing = True
        host._animation_playback_pre_callback(self.scene)
        self.scene.frame_current = 2
        host._frame_change_post_callback(self.scene)
        self.screen.is_animation_playing = False
        host._animation_playback_post_callback(self.scene)
        self.scene.frame_current = 5
        host._frame_change_post_callback(self.scene)
        self.assertEqual(
            [
                PlaybackHostEventKind.PLAY_STARTED,
                PlaybackHostEventKind.PLAY_STOPPED,
                PlaybackHostEventKind.PAUSED_SEEK,
            ],
            [event.kind for event in self.events],
        )

    def test_snapshot_rejects_non_owner_thread(self):
        errors = []

        def read_snapshot():
            try:
                self.host.snapshot()
            except Exception as error:  # noqa: BLE001 - thread boundary assertion
                errors.append(error)

        thread = threading.Thread(target=read_snapshot)
        thread.start()
        thread.join()
        self.assertEqual(1, len(errors))
        self.assertIsInstance(errors[0], BlenderPlaybackHostError)
        self.assertIn("Main Thread", str(errors[0]))

    def test_apply_port_requires_matching_query_port(self):
        with self.assertRaisesRegex(BlenderPlaybackHostError, "speed_apply requires speed_query"):
            BlenderPlaybackHost(
                self.events.append,
                bpy_module=self.bpy,
                speed_apply=lambda _scene, _speed: None,
            )
        with self.assertRaisesRegex(BlenderPlaybackHostError, "loop_mode_apply requires loop_mode_query"):
            BlenderPlaybackHost(
                self.events.append,
                bpy_module=self.bpy,
                loop_mode_apply=lambda _scene, _mode: None,
            )

    def test_register_and_unregister_are_idempotent(self):
        self.assertTrue(self.host.register())
        self.assertFalse(self.host.register())
        for name in BLENDER_PLAYBACK_HANDLERS:
            self.assertEqual(1, len(getattr(self.bpy.app.handlers, name)))
        self.assertEqual(1, len(self.bpy.app.timers.callbacks))
        self.assertTrue(self.bpy.app.timers.callbacks[0][2])
        self.assertTrue(self.host.unregister())
        self.assertFalse(self.host.unregister())
        for name in BLENDER_PLAYBACK_HANDLERS:
            self.assertEqual([], getattr(self.bpy.app.handlers, name))
        self.assertEqual([], self.bpy.app.timers.callbacks)

    def test_register_collapses_preexisting_duplicate_callback(self):
        self.host.register()
        self.host.unregister()
        callback = self.host._callback_map()["frame_change_post"]
        handler = self.bpy.app.handlers.frame_change_post
        handler.extend((callback, callback))
        self.assertTrue(self.host.register())
        self.assertEqual(1, sum(existing == callback for existing in handler))

    def test_unregister_failure_retains_actual_handlers_for_retry(self):
        class FailingList(list):
            def __init__(self):
                super().__init__()
                self.fail = True

            def remove(self, value):
                if self.fail:
                    raise RuntimeError("handler removal failed")
                return super().remove(value)

        failing = FailingList()
        self.bpy.app.handlers.frame_change_post = failing
        self.host.register()
        with self.assertRaises(BlenderPlaybackHostError):
            self.host.unregister()
        self.assertTrue(self.host.registered)
        self.assertEqual(1, len(failing))
        failing.fail = False
        self.assertTrue(self.host.unregister())
        self.assertFalse(self.host.registered)

    def test_stable_wrappers_accept_extra_arguments_and_survive_file_load(self):
        self.host.register()
        wrappers = self.host._callback_map()
        for callback in wrappers.values():
            self.assertTrue(getattr(callback, "persistent", False))
        self.bpy.app.handlers.simulate_file_load()
        self.assertIs(wrappers["frame_change_post"], self.bpy.app.handlers.frame_change_post[0])
        wrappers["animation_playback_pre"](self.scene, object())
        self.assertTrue(self.host._pending_start)

    def test_direction_is_determined_by_forward_frame_delta(self):
        self.host.register()
        self.screen.is_animation_playing = True
        self.host._animation_playback_pre_callback(self.scene)
        self.scene.frame_current = 2
        self.host._frame_change_post_callback(self.scene)
        self.assertEqual([PlaybackHostEventKind.PLAY_STARTED], [event.kind for event in self.events])
        self.assertEqual("forward", self.events[0].snapshot.direction)

    def test_direction_is_determined_by_reverse_frame_delta(self):
        self.host.register()
        self.screen.is_animation_playing = True
        self.host._animation_playback_pre_callback(self.scene)
        self.scene.frame_current = 0
        self.host._frame_change_post_callback(self.scene)
        self.assertEqual("reverse", self.events[0].snapshot.direction)

    def test_query_can_determine_start_before_first_frame_delta(self):
        host = BlenderPlaybackHost(
            self.events.append,
            bpy_module=self.bpy,
            playback_control=self._control,
            direction_query=lambda: "reverse",
        )
        host.register()
        self.screen.is_animation_playing = True
        host._animation_playback_pre_callback(self.scene)
        self.assertEqual(PlaybackHostEventKind.PLAY_STARTED, self.events[0].kind)
        self.assertEqual("reverse", self.events[0].snapshot.direction)

    def test_playing_frame_changes_are_suppressed(self):
        self.host.register()
        self.screen.is_animation_playing = True
        self.host._animation_playback_pre_callback(self.scene)
        self.scene.frame_current = 2
        self.host._frame_change_post_callback(self.scene)
        self.scene.frame_current = 3
        self.host._frame_change_post_callback(self.scene)
        self.assertEqual([PlaybackHostEventKind.PLAY_STARTED], [event.kind for event in self.events])

    def test_paused_frame_change_is_a_seek_event(self):
        self.host.register()
        self.scene.frame_current = 5
        self.host._frame_change_post_callback(self.scene)
        self.assertEqual([PlaybackHostEventKind.PAUSED_SEEK], [event.kind for event in self.events])
        self.assertEqual(5, self.events[0].snapshot.position)

    def test_stop_reports_final_position_once(self):
        self.host.register()
        self.screen.is_animation_playing = True
        self.host._animation_playback_pre_callback(self.scene)
        self.scene.frame_current = 2
        self.host._frame_change_post_callback(self.scene)
        self.scene.frame_current = 9
        self.screen.is_animation_playing = False
        self.host._animation_playback_post_callback(self.scene)
        self.host._frame_change_post_callback(self.scene)
        self.assertEqual(
            [PlaybackHostEventKind.PLAY_STARTED, PlaybackHostEventKind.PLAY_STOPPED],
            [event.kind for event in self.events],
        )
        self.assertEqual(9, self.events[-1].snapshot.position)

    def test_range_speed_and_loop_are_detected_by_tick(self):
        loop_mode = ["once"]
        speed = [1.0]
        host = BlenderPlaybackHost(
            self.events.append,
            bpy_module=self.bpy,
            playback_control=self._control,
            loop_mode_query=lambda _scene: loop_mode[0],
            speed_query=lambda _scene: speed[0],
        )
        host.register()
        self.scene.frame_end = 30
        loop_mode[0] = "loop"
        speed[0] = 2.0
        host.tick()
        self.assertEqual(
            [
                PlaybackHostEventKind.RANGE_CHANGED,
                PlaybackHostEventKind.SPEED_CHANGED,
                PlaybackHostEventKind.MODE_CHANGED,
            ],
            [event.kind for event in self.events],
        )

    def test_range_conversion_uses_exclusive_wire_end_and_frame_step(self):
        wire = self.host.blender_range_to_wire(1, 24, frame_step=2)
        self.assertEqual(PlaybackHostRange(1, 26), wire)
        self.assertEqual((1, 24), self.host.wire_range_to_blender(wire, frame_step=2))

    def test_single_frame_range_is_valid(self):
        self.scene.frame_start = 10
        self.scene.frame_end = 10
        self.host.register()
        self.scene.frame_current = 10
        self.host._frame_change_post_callback(self.scene)
        self.assertEqual(PlaybackHostRange(10, 11), self.events[0].snapshot.playback_range)

    def test_remote_apply_maps_range_speed_and_suppresses_echo(self):
        self.host.register()
        self.host.apply(_snapshot(state="paused"))
        self.assertEqual([], self.events)
        self.assertEqual(1.0, self.scene.frame_start)
        self.assertEqual(24.0, self.scene.frame_end)
        self.assertEqual(12.0, self.scene.frame_current)
        self.assertEqual(1.0, self.scene.render.fps_base)
        self.assertEqual(("speed", "loop_mode"), self.host.last_apply_approximated_fields)
        self.assertEqual([], self.controls)

    def test_remote_apply_rejects_mapping_without_mutating_blender(self):
        initial = (self.scene.frame_start, self.scene.frame_end, self.scene.frame_current)

        with self.assertRaisesRegex(BlenderPlaybackHostError, "PlaybackHostSnapshot"):
            self.host.apply({"state": "paused"})  # type: ignore[arg-type]

        self.assertEqual(initial, (self.scene.frame_start, self.scene.frame_end, self.scene.frame_current))
        self.assertEqual([], self.controls)

    def test_remote_play_apply_uses_control_port(self):
        self.host.register()
        self.host.apply(_snapshot(state="playing", direction="forward"))
        self.assertEqual([("play", "forward")], self.controls)
        self.assertEqual([], self.events)

    def test_remote_apply_stops_existing_playback_before_mapping(self):
        self.host.register()
        self.screen.is_animation_playing = True
        self.host.apply(_snapshot())
        self.assertEqual([("stop", None)], self.controls)

    def test_preview_range_is_read_and_applied_without_touching_normal_range(self):
        self.scene.use_preview_range = True
        self.scene.frame_preview_start = 10
        self.scene.frame_preview_end = 20
        self.host.register()
        self.scene.frame_current = 5
        self.host._frame_change_post_callback(self.scene)
        self.assertEqual(PlaybackHostRange(10, 21), self.events[0].snapshot.playback_range)
        self.host.apply(_snapshot(position=12.5, playback_range=PlaybackHostRange(3, 9)))
        self.assertEqual((1, 24), (self.scene.frame_start, self.scene.frame_end))
        self.assertEqual((3, 8), (self.scene.frame_preview_start, self.scene.frame_preview_end))
        self.assertEqual((12, 0.5), (self.scene.frame_current, self.scene.frame_subframe))

    def test_fractional_range_boundary_is_rejected_without_coercion(self):
        self.host.register()
        with self.assertRaises(BlenderPlaybackHostError):
            self.host.apply(_snapshot(playback_range=PlaybackHostRange(1.5, 25)))

    def test_reverse_remote_apply_preserves_direction_for_stop_snapshot(self):
        self.host.register()
        self.host.apply(_snapshot(state="playing", direction="reverse"))
        self.screen.is_animation_playing = False
        self.host._animation_playback_post_callback(self.scene)
        self.assertEqual("reverse", self.events[-1].snapshot.direction)

    def test_range_wrap_waits_for_the_next_delta_before_start_direction(self):
        self.scene.frame_current = 24
        self.host.register()
        self.screen.is_animation_playing = True
        self.host._animation_playback_pre_callback(self.scene)
        self.scene.frame_current = 1
        self.host._frame_change_post_callback(self.scene)
        self.assertEqual([], self.events)
        self.scene.frame_current = 2
        self.host._frame_change_post_callback(self.scene)
        self.assertEqual("forward", self.events[0].snapshot.direction)

    def test_render_frame_change_is_fail_safe_and_foreign_thread_is_not_published(self):
        render = [True]
        host = BlenderPlaybackHost(
            self.events.append,
            bpy_module=self.bpy,
            playback_control=self._control,
            job_running_query=lambda: render[0],
        )
        host.register()
        self.scene.frame_current = 5
        host._frame_change_post_callback(self.scene)
        self.assertEqual([], self.events)
        render[0] = False

        def callback():
            host._frame_change_post_callback(self.scene)

        thread = threading.Thread(target=callback)
        thread.start()
        thread.join()
        self.assertEqual([], self.events)
        self.assertIsNotNone(host.last_error)
        self.assertIn("Main Thread", host.last_error.message)

    def test_apply_is_restricted_to_owner_thread(self):
        errors = []

        def apply_remote():
            try:
                self.host.apply(_snapshot())
            except Exception as error:  # noqa: BLE001 - thread boundary assertion
                errors.append(error)

        self.host.register()
        thread = threading.Thread(target=apply_remote)
        thread.start()
        thread.join()
        self.assertEqual(1, len(errors))
        self.assertIsInstance(errors[0], BlenderPlaybackHostError)
        self.assertIn("Main Thread", str(errors[0]))

    def test_callback_exception_isolated_and_observable(self):
        def fail(_event):
            raise ValueError("controller failed")

        host = BlenderPlaybackHost(fail, bpy_module=self.bpy, playback_control=self._control)
        host.register()
        self.scene.frame_current = 5
        self.host = host
        host._frame_change_post_callback(self.scene)
        self.assertIsNotNone(host.last_error)
        self.assertEqual("ValueError", host.last_error.exception_type)
        self.assertEqual(1, host.last_error.count)

    def test_timer_callback_does_not_leak_scene_error(self):
        host = BlenderPlaybackHost(self.events.append, bpy_module=self.bpy, playback_control=self._control)
        host.register()
        self.scene.frame_end = object()
        self.assertEqual(0.1, host._timer_callback_wrapper())
        self.assertEqual("BlenderPlaybackHostError", host.last_error.exception_type)


if __name__ == "__main__":
    unittest.main()
