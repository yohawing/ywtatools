"""Maya Playback Host bridgeのcallback/apply境界を検証する。"""

import threading
import unittest
from unittest import mock

import ywta.link.playback_host as playback_host
from ywta_link.playback_host import (
    PlaybackHostEventKind,
    PlaybackHostRange,
    PlaybackHostSnapshot,
)
from ywta.link.playback_host import (
    MayaPlaybackHost,
    MayaPlaybackHostError,
    MayaPlaybackHostUnavailableError,
)


class _FakeTime:
    """MTimeの最小依存を再現する。"""

    kFilm = 1
    kNtsc = 2
    kSeconds = 3

    @classmethod
    def uiUnit(cls):
        return cls.kFilm

    def __init__(self, value, unit=None):
        self.value = value
        self.unit = unit


class _FakeAnim:
    """MAnimControlのstatic APIを記録するfake。"""

    kPlaybackOnce = 1
    kPlaybackLoop = 2
    kPlaybackOscillate = 3

    def __init__(self):
        self.current = 10.0
        self.minimum = 1.0
        self.maximum = 24.0
        self.playing = False
        self.speed = 1.0
        self.by = 1.0
        self.mode = self.kPlaybackOnce
        self.calls = []

    def currentTime(self):
        return _FakeTime(self.current)

    def minTime(self):
        return _FakeTime(self.minimum)

    def maxTime(self):
        return _FakeTime(self.maximum)

    def isPlaying(self):
        return self.playing

    def playbackSpeed(self):
        return self.speed

    def playbackBy(self):
        return self.by

    def playbackMode(self):
        return self.mode

    def stop(self):
        self.calls.append(("stop",))
        self.playing = False

    def play(self):
        self.calls.append(("play",))
        self.playing = True

    def playForward(self):
        self.calls.append(("playForward",))
        self.playing = True

    def playBackward(self):
        self.calls.append(("playBackward",))
        self.playing = True

    def setMinMaxTime(self, start, end):
        self.calls.append(("setMinMaxTime", start.value, end.value))
        self.minimum = start.value
        self.maximum = end.value

    def setPlaybackSpeed(self, speed):
        self.calls.append(("setPlaybackSpeed", speed))
        self.speed = speed

    def setPlaybackBy(self, by):
        self.calls.append(("setPlaybackBy", by))
        self.by = by

    def setPlaybackMode(self, mode):
        self.calls.append(("setPlaybackMode", mode))
        self.mode = mode

    def setCurrentTime(self, current):
        self.calls.append(("setCurrentTime", current.value))
        self.current = current.value


class _FakeConditionMessage:
    callback = None

    @classmethod
    def addConditionCallback(cls, name, callback):
        assert name == "playingBack"
        cls.callback = callback
        return "condition-id"


class _FakeEventMessage:
    callbacks = {}

    @classmethod
    def addEventCallback(cls, name, callback):
        cls.callbacks[name] = callback
        return "event-{}".format(name)


class _FakeMessage:
    removed = []
    fail_ids = set()

    @classmethod
    def removeCallback(cls, callback_id):
        if callback_id in cls.fail_ids:
            raise RuntimeError("remove failed")
        cls.removed.append(callback_id)


class _FakeApi:
    MTime = _FakeTime
    MAnimControl = _FakeAnim
    MConditionMessage = _FakeConditionMessage
    MEventMessage = _FakeEventMessage
    MMessage = _FakeMessage


def _snapshot(**changes):
    """テスト用のremote snapshotを作る。"""

    value = {
        "state": "paused",
        "position": 12.0,
        "playback_range": PlaybackHostRange(1.0, 25.0),
        "speed": 2.0,
        "direction": "reverse",
        "loop_mode": "loop",
        "time_unit": "film",
        "change_id": "remote-001",
    }
    value.update(changes)
    return PlaybackHostSnapshot(**value)


class MayaPlaybackHostTests(unittest.TestCase):
    """Maya APIを使わないPlayback bridgeの契約テスト。"""

    def setUp(self):
        _FakeConditionMessage.callback = None
        _FakeEventMessage.callbacks = {}
        _FakeMessage.removed = []
        _FakeMessage.fail_ids = set()
        self.anim = _FakeAnim()
        self.events = []
        self.host = MayaPlaybackHost(
            self.events.append,
            api=_FakeApi,
            anim_control=self.anim,
            time_unit=_FakeTime.kFilm,
            time_unit_label="film",
            time_unit_label_provider=lambda: "film",
        )

    def test_import_dependency_is_reported_at_constructor(self):
        with mock.patch.object(playback_host, "_OPEN_MAYA", None):
            with self.assertRaises(MayaPlaybackHostUnavailableError):
                MayaPlaybackHost(lambda _event: None, api=None)

    def test_string_time_unit_is_rejected_at_constructor(self):
        with self.assertRaisesRegex(MayaPlaybackHostError, "enum"):
            MayaPlaybackHost(self.events.append, api=_FakeApi, anim_control=self.anim, time_unit="film")

    def test_snapshot_returns_typed_current_state_without_registration(self):
        snapshot = self.host.snapshot()
        self.assertIs(type(snapshot), PlaybackHostSnapshot)
        self.assertEqual(10.0, snapshot.position)
        self.assertEqual(PlaybackHostRange(1.0, 25.0), snapshot.playback_range)

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
        self.assertIsInstance(errors[0], MayaPlaybackHostError)
        self.assertIn("Main Thread", str(errors[0]))

    def test_register_and_unregister_are_idempotent(self):
        self.assertTrue(self.host.register())
        self.assertFalse(self.host.register())
        self.assertEqual(5, len(self.host.callback_ids))
        self.assertTrue(self.host.unregister())
        self.assertFalse(self.host.unregister())
        self.assertEqual(
            [
                "condition-id",
                "event-timeChanged",
                "event-playbackRangeChanged",
                "event-playbackSpeedChanged",
                "event-playbackModeChanged",
            ],
            _FakeMessage.removed,
        )

    def test_register_validates_time_unit_before_mutating_callback_state(self):
        host = MayaPlaybackHost(
            self.events.append,
            api=_FakeApi,
            anim_control=self.anim,
            time_unit=_FakeTime.kFilm,
            time_unit_label="film",
            time_unit_label_provider=lambda: "ntsc",
        )

        with self.assertRaisesRegex(MayaPlaybackHostError, "time unit"):
            host.register()

        self.assertFalse(host.registered)
        self.assertEqual((), host.callback_ids)
        self.assertEqual([], self.anim.calls)

    def test_unregister_failure_retains_ids_for_retry(self):
        self.host.register()
        _FakeMessage.fail_ids = {"event-playbackRangeChanged"}
        with self.assertRaises(MayaPlaybackHostError):
            self.host.unregister()
        self.assertTrue(self.host.registered)
        self.assertEqual(("event-playbackRangeChanged",), self.host.callback_ids)
        self.assertEqual(
            [
                "condition-id",
                "event-timeChanged",
                "event-playbackSpeedChanged",
                "event-playbackModeChanged",
            ],
            _FakeMessage.removed,
        )
        _FakeMessage.fail_ids = set()
        self.assertTrue(self.host.unregister())

    def test_non_callable_direction_query_is_rejected(self):
        with self.assertRaises(MayaPlaybackHostError):
            MayaPlaybackHost(
                self.events.append,
                api=_FakeApi,
                anim_control=self.anim,
                direction_query=False,
            )

    def test_injected_api_does_not_use_real_maya_direction_query(self):
        host = MayaPlaybackHost(
            self.events.append,
            api=_FakeApi,
            anim_control=self.anim,
        )
        host.register()
        _FakeConditionMessage.callback(True)
        self.assertEqual("forward", self.events[0].snapshot.direction)

    def test_register_failure_cleanup_success_clears_partial_ids(self):
        class FailingEvents:
            calls = 0

            @classmethod
            def addEventCallback(cls, name, callback):
                cls.calls += 1
                if cls.calls == 2:
                    raise RuntimeError("register failed")
                return "partial-event-{}".format(name)

        class FailingApi(_FakeApi):
            MEventMessage = FailingEvents

        host = MayaPlaybackHost(self.events.append, api=FailingApi, anim_control=self.anim, time_unit=_FakeTime.kFilm)
        with self.assertRaises(MayaPlaybackHostError):
            host.register()
        self.assertFalse(host.registered)
        self.assertEqual((), host.callback_ids)

    def test_register_failure_cleanup_failure_keeps_partial_state_for_unregistration(self):
        class FailingEvents:
            calls = 0

            @classmethod
            def addEventCallback(cls, name, callback):
                cls.calls += 1
                if cls.calls == 2:
                    raise RuntimeError("register failed")
                return "partial-event-{}".format(name)

        class FailingCleanupMessage:
            @classmethod
            def removeCallback(cls, callback_id):
                raise RuntimeError("cleanup failed")

        self.assertEqual(0, len(self.anim.calls))

        class FailingApi(_FakeApi):
            MEventMessage = FailingEvents
            MMessage = FailingCleanupMessage

        host = MayaPlaybackHost(self.events.append, api=FailingApi, anim_control=self.anim, time_unit=_FakeTime.kFilm)
        with self.assertRaises(MayaPlaybackHostError) as context:
            host.register()
        self.assertIn("cleanup failed", str(context.exception))
        self.assertTrue(host.registered)
        self.assertEqual(2, len(host.callback_ids))

    def test_register_initial_state_failure_rolls_back_callbacks(self):
        class FailingAnim(_FakeAnim):
            def isPlaying(self):
                raise RuntimeError("state read failed")

        anim = FailingAnim()
        host = MayaPlaybackHost(self.events.append, api=_FakeApi, anim_control=anim, time_unit=_FakeTime.kFilm)
        with self.assertRaises(MayaPlaybackHostError) as context:
            host.register()
        self.assertIsInstance(context.exception.__cause__, RuntimeError)
        self.assertFalse(host.registered)
        self.assertEqual((), host.callback_ids)

    def test_injected_direction_query_controls_backward_start_snapshot(self):
        host = MayaPlaybackHost(
            self.events.append,
            api=_FakeApi,
            anim_control=self.anim,
            time_unit=_FakeTime.kFilm,
            direction_query=lambda: False,
        )
        host.register()
        _FakeConditionMessage.callback(True)
        self.assertEqual(PlaybackHostEventKind.PLAY_STARTED, self.events[0].kind)
        self.assertEqual("reverse", self.events[0].snapshot.direction)

    def test_direction_query_none_or_failure_keeps_previous_direction(self):
        query_values = iter((False, None))

        def query():
            return next(query_values)

        host = MayaPlaybackHost(
            self.events.append,
            api=_FakeApi,
            anim_control=self.anim,
            time_unit=_FakeTime.kFilm,
            direction_query=query,
        )
        host.register()
        _FakeConditionMessage.callback(True)
        _FakeEventMessage.callbacks["playbackModeChanged"]("playbackModeChanged")
        self.assertEqual(["reverse", "reverse"], [event.snapshot.direction for event in self.events])

        failing_host = MayaPlaybackHost(
            self.events.append,
            api=_FakeApi,
            anim_control=self.anim,
            time_unit=_FakeTime.kFilm,
            direction_query=lambda: (_ for _ in ()).throw(RuntimeError("query failed")),
        )
        failing_host.register()
        _FakeEventMessage.callbacks["playbackModeChanged"]("playbackModeChanged")
        self.assertEqual("forward", failing_host._last_direction)
        self.assertEqual("direction_query", failing_host.last_error.callback)

    def test_playing_time_changed_is_suppressed(self):
        self.host.register()
        _FakeConditionMessage.callback(True)
        _FakeEventMessage.callbacks["timeChanged"]("timeChanged")
        self.assertEqual([PlaybackHostEventKind.PLAY_STARTED], [event.kind for event in self.events])

    def test_paused_time_changed_is_a_seek_event(self):
        self.host.register()
        _FakeEventMessage.callbacks["timeChanged"]("timeChanged")
        self.assertEqual([PlaybackHostEventKind.PAUSED_SEEK], [event.kind for event in self.events])
        self.assertEqual(10.0, self.events[0].snapshot.position)

    def test_play_start_and_stop_are_edges(self):
        self.host.register()
        _FakeConditionMessage.callback(True)
        _FakeConditionMessage.callback(True)
        _FakeConditionMessage.callback(False)
        _FakeConditionMessage.callback(False)
        self.assertEqual(
            [PlaybackHostEventKind.PLAY_STARTED, PlaybackHostEventKind.PLAY_STOPPED],
            [event.kind for event in self.events],
        )

    def test_range_speed_and_mode_callbacks_emit_typed_events(self):
        self.host.register()
        for event_name in ("playbackRangeChanged", "playbackSpeedChanged", "playbackModeChanged"):
            _FakeEventMessage.callbacks[event_name](event_name)
        self.assertEqual(
            [
                PlaybackHostEventKind.RANGE_CHANGED,
                PlaybackHostEventKind.SPEED_CHANGED,
                PlaybackHostEventKind.MODE_CHANGED,
            ],
            [event.kind for event in self.events],
        )

    def test_zero_playback_speed_is_explicitly_approximated(self):
        self.host.register()
        self.anim.speed = 0.0
        _FakeEventMessage.callbacks["playbackSpeedChanged"]("playbackSpeedChanged")
        snapshot = self.events[0].snapshot
        self.assertEqual(1.0, snapshot.speed)
        self.assertEqual(("speed",), snapshot.approximated_fields)

    def test_positive_playback_speed_has_no_approximation(self):
        self.host.register()
        _FakeEventMessage.callbacks["playbackSpeedChanged"]("playbackSpeedChanged")
        self.assertEqual((), self.events[0].snapshot.approximated_fields)

    def test_range_conversion_uses_exclusive_wire_end(self):
        wire = self.host.maya_range_to_wire(1, 24)
        self.assertEqual(PlaybackHostRange(1, 25.0), wire)
        self.assertEqual((1, 24.0), self.host.wire_range_to_maya(wire))

    def test_apply_sets_range_time_mode_direction_and_state_without_echo(self):
        self.host.register()
        self.host.apply(_snapshot(state="playing"))
        self.assertEqual([], self.events)
        self.assertEqual(
            [
                ("stop",),
                ("setMinMaxTime", 1.0, 24.0),
                ("setPlaybackSpeed", 2.0),
                ("setPlaybackBy", 1.0),
                ("setPlaybackMode", _FakeAnim.kPlaybackLoop),
                ("setCurrentTime", 12.0),
                ("playBackward",),
            ],
            self.anim.calls,
        )

    def test_apply_rejects_mapping_without_mutating_maya(self):
        with self.assertRaisesRegex(MayaPlaybackHostError, "PlaybackHostSnapshot"):
            self.host.apply({"state": "paused"})  # type: ignore[arg-type]

        self.assertEqual([], self.anim.calls)

    def test_apply_uses_mtime_ui_unit_enum(self):
        class RecordingAnim(_FakeAnim):
            def __init__(self):
                super().__init__()
                self.mtime_units = []

            def setMinMaxTime(self, start, end):
                self.mtime_units.extend((start.unit, end.unit))
                super().setMinMaxTime(start, end)

            def setCurrentTime(self, current):
                self.mtime_units.append(current.unit)
                super().setCurrentTime(current)

        anim = RecordingAnim()
        host = MayaPlaybackHost(
            self.events.append,
            api=_FakeApi,
            anim_control=anim,
            time_unit=_FakeTime.kFilm,
            time_unit_label="film",
            time_unit_label_provider=lambda: "film",
        )
        host.apply(_snapshot())

        self.assertEqual([_FakeTime.kFilm, _FakeTime.kFilm, _FakeTime.kFilm], anim.mtime_units)

    def test_time_unit_drift_fails_closed_for_snapshot_and_apply(self):
        current_label = ["film"]
        host = MayaPlaybackHost(
            self.events.append,
            api=_FakeApi,
            anim_control=self.anim,
            time_unit=_FakeTime.kFilm,
            time_unit_label="film",
            time_unit_label_provider=lambda: current_label[0],
        )
        self.assertIsInstance(host.snapshot(), PlaybackHostSnapshot)
        current_label[0] = "ntsc"

        with self.assertRaisesRegex(MayaPlaybackHostError, "time unit"):
            host.snapshot()
        with self.assertRaisesRegex(MayaPlaybackHostError, "time unit"):
            host.apply(_snapshot())
        self.assertEqual([], self.anim.calls)

    def test_time_unit_drift_is_isolated_in_callback_status(self):
        current_label = ["film"]
        host = MayaPlaybackHost(
            self.events.append,
            api=_FakeApi,
            anim_control=self.anim,
            time_unit=_FakeTime.kFilm,
            time_unit_label="film",
            time_unit_label_provider=lambda: current_label[0],
        )
        host.register()
        current_label[0] = "ntsc"
        _FakeEventMessage.callbacks["timeChanged"]("timeChanged")

        self.assertEqual([], self.events)
        self.assertIsNotNone(host.last_error)
        self.assertEqual("MayaPlaybackHostError", host.last_error.exception_type)
        self.assertEqual("timeChanged", host.last_error.callback)

    def test_apply_rejects_non_owner_thread(self):
        errors = []

        def apply_remote():
            try:
                self.host.apply(_snapshot())
            except Exception as error:  # noqa: BLE001 - thread boundary assertion
                errors.append(error)

        thread = threading.Thread(target=apply_remote)
        thread.start()
        thread.join()
        self.assertEqual(1, len(errors))
        self.assertIsInstance(errors[0], MayaPlaybackHostError)
        self.assertIn("Main Thread", str(errors[0]))

    def test_callback_exception_isolated_and_observable(self):
        def fail(_event):
            raise ValueError("controller failed")

        host = MayaPlaybackHost(fail, api=_FakeApi, anim_control=self.anim, time_unit=_FakeTime.kFilm)
        host.register()
        _FakeEventMessage.callbacks["timeChanged"]("timeChanged")
        self.assertIsNotNone(host.last_error)
        self.assertEqual("ValueError", host.last_error.exception_type)
        self.assertEqual(1, host.last_error.count)


if __name__ == "__main__":
    unittest.main()
