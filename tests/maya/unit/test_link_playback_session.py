"""Maya向けPlayback Session compositionを検証する。"""

import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest import mock

import ywta.link.session as maya_session
import ywta.link.playback_host as maya_playback_host
from ywta.link import (
    MayaPlaybackHost,
    MayaPlaybackLifecycle,
    bootstrap_maya_playback_session,
    compose_maya_playback_session,
    default_maya_playback_config,
)
from ywta_link import PlaybackBootstrapError, PlaybackSessionConfig, PlaybackSessionError, RationalRate


class _Signal:
    """QTimer.timeoutの最小fake。"""

    def connect(self, callback):
        self.callback = callback


class _Timer:
    """QTimerの注入境界を再現するfake。"""

    def __init__(self):
        self.timeout = _Signal()
        self.interval = None
        self.started = False

    def setInterval(self, interval):
        self.interval = interval

    def start(self):
        self.started = True

    def stop(self):
        self.started = False


class _Anim:
    """MAnimControlの未開始composition用fake。"""

    kPlaybackOnce = 1

    def isPlaying(self):
        return False

    def currentTime(self):
        return 1.0

    def minTime(self):
        return 1.0

    def maxTime(self):
        return 24.0

    def playbackSpeed(self):
        return 1.0

    def playbackBy(self):
        return 1.0

    def playbackMode(self):
        return self.kPlaybackOnce


class _Api:
    """Maya API引数の最小fake。"""

    MAnimControl = _Anim


class _MTime:
    """MTimeのUI unitと秒変換を再現するfake。"""

    kFilm = 1
    kNtsc = 2
    kSeconds = 3
    ui_unit = kFilm
    seconds = 1.0 / 24.0

    @classmethod
    def uiUnit(cls):
        return cls.ui_unit

    def __init__(self, value, unit):
        self.value = value
        self.unit = unit

    def asUnits(self, unit):
        if unit != self.kSeconds:
            raise ValueError(unit)
        return self.seconds


class _BootstrapApi:
    """default bootstrap用のMaya API fake。"""

    MTime = _MTime


_Api.MTime = _MTime


class _Cmds:
    """Playback default設定のqueryを記録するcmds fake。"""

    def __init__(self, time_unit="film", version="2024"):
        self.time_unit = time_unit
        self.version = version
        self.calls = []

    def currentUnit(self, **kwargs):
        self.calls.append(("currentUnit", kwargs))
        return self.time_unit

    def about(self, **kwargs):
        self.calls.append(("about", kwargs))
        return self.version


class _SceneMessage:
    """MSceneMessageの未開始composition用fake。"""

    kMayaExiting = "mayaExiting"

    def addCallback(self, event, callback):
        return "exit-id"


class _Message:
    """MMessageの未開始composition用fake。"""

    def removeCallback(self, callback_id):
        pass


class _Client:
    """専用Clientの最小fake。"""

    def __init__(self):
        self.peer_id = "maya:peer-001"
        self.events = []

    def join(self, room):
        self.events.append(("join", room))

    def close(self):
        self.events.append(("close",))

    def receive(self, timeout=None):
        raise RuntimeError("not started")

    def publish(self, *args, **kwargs):
        return "message-id"

    def request(self, *args, **kwargs):
        return kwargs.get("message_id", "request-id")

    def response(self, *args, **kwargs):
        return "response-id"

    def subscribe(self, *args):
        return "subscription-id"

    def unsubscribe(self, *args):
        return None


def _config(**changes):
    """テスト用にRoom、Authority、timebaseを明示する。"""

    values = {
        "peer_id": "maya:peer-001",
        "session_id": "session-001",
        "room": "room-001",
        "topic": "playback",
        "channel_id": "playback-main",
        "initial_authority": "maya:peer-001",
        "ticks_per_host_unit": 1,
        "host_unit_rate": RationalRate(24, 1),
        "time_unit": "film",
    }
    values.update(changes)
    return PlaybackSessionConfig(
        **values,
    )


class MayaPlaybackSessionTests(unittest.TestCase):
    """Maya importなしの標準Python compositionテスト。"""

    def test_composes_maya_host_lifecycle_and_closes_client_before_start(self):
        client = _Client()
        timer = _Timer()
        session = compose_maya_playback_session(
            _config(),
            timer=timer,
            scene_message=_SceneMessage(),
            message=_Message(),
            client_factory=lambda config: client,
            host_options={"api": _Api, "anim_control": _Anim()},
            lifecycle_options={"timer_interval_ms": 25},
        )

        self.assertIsInstance(session.lifecycle, MayaPlaybackLifecycle)
        self.assertIsInstance(session.lifecycle._host, MayaPlaybackHost)
        self.assertEqual(_MTime.kFilm, session.lifecycle._host.time_unit)
        self.assertEqual("film", session.lifecycle._host.time_unit_label)
        self.assertIs(session.lifecycle._timer, timer)
        self.assertEqual(25, timer.interval)
        self.assertEqual([("join", "room-001")], client.events)

        self.assertTrue(session.close())
        self.assertEqual([("join", "room-001"), ("close",)], client.events)
        self.assertFalse(timer.started)

    def test_reserved_options_are_rejected_before_client_creation(self):
        cases = (
            ("on_change", {"host_options": {"on_change": lambda event: None}}),
            ("time_unit", {"host_options": {"time_unit": _MTime.kFilm}}),
            ("time_unit_label", {"host_options": {"time_unit_label": "film"}}),
            ("runtime", {"lifecycle_options": {"runtime": object()}}),
            ("host", {"lifecycle_options": {"host": object()}}),
            ("timer", {"lifecycle_options": {"timer": object()}}),
            ("scene_message", {"lifecycle_options": {"scene_message": object()}}),
            ("message", {"lifecycle_options": {"message": object()}}),
        )
        for key, options in cases:
            with self.subTest(key=key):
                with self.assertRaisesRegex(PlaybackSessionError, key):
                    compose_maya_playback_session(
                        _config(),
                        client_factory=lambda config: self.fail("Client factory must not run"),
                        **options,
                    )

    def test_default_config_reads_maya_identity_and_24fps_rate(self):
        cmds = _Cmds()
        config = default_maya_playback_config(cmds_module=cmds, api=_BootstrapApi)

        self.assertEqual("maya", config.application_id)
        self.assertEqual("Autodesk Maya", config.application)
        self.assertEqual("2024", config.application_version)
        self.assertEqual("0.1.0", config.plugin_version)
        self.assertEqual("film", config.time_unit)
        self.assertEqual(RationalRate(24, 1), config.host_unit_rate)
        self.assertEqual(("currentUnit", {"q": True, "time": True}), cmds.calls[0])
        self.assertEqual(("currentUnit", {"q": True, "time": True}), cmds.calls[1])
        self.assertEqual(("about", {"version": True}), cmds.calls[2])

    def test_default_config_converts_ntsc_rate_to_reduced_rational(self):
        _MTime.ui_unit = _MTime.kNtsc
        _MTime.seconds = 1001.0 / 24000.0

        try:
            config = default_maya_playback_config(cmds_module=_Cmds(time_unit="ntsc"), api=_BootstrapApi)
        finally:
            _MTime.ui_unit = _MTime.kFilm
            _MTime.seconds = 1.0 / 24.0

        self.assertEqual(RationalRate(24000, 1001), config.host_unit_rate)
        self.assertEqual(5005, config.ticks_per_host_unit)

    def test_default_bootstrap_passes_same_time_unit_to_maya_host_and_lifecycle(self):
        cmds = _Cmds(time_unit="ntsc")
        captured = {}

        def fake_bootstrap(config, host_factory, lifecycle_factory, connection_factory):
            captured["config"] = config
            captured["host"] = host_factory
            captured["lifecycle"] = lifecycle_factory
            captured["connection_factory"] = connection_factory
            return SimpleNamespace(started=False, lifecycle="unstarted")

        timer = _Timer()
        with mock.patch.object(maya_session, "bootstrap_playback_session", fake_bootstrap):
            session = bootstrap_maya_playback_session(
                cmds_module=cmds,
                api=_BootstrapApi,
                connection_factory="connection-factory",
                timer=timer,
                scene_message=_SceneMessage(),
                message=_Message(),
                host_options={"anim_control": _Anim()},
            )

        self.assertFalse(session.started)
        host = captured["host"](lambda _event: None)
        self.assertIsInstance(host, MayaPlaybackHost)
        self.assertEqual(_MTime.kFilm, host._time_unit)
        self.assertEqual("ntsc", host.time_unit_label)
        self.assertIs(captured["connection_factory"], "connection-factory")
        self.assertEqual("ntsc", captured["config"].time_unit)

        runtime = SimpleNamespace(start=lambda: True, pump=lambda: None, close=lambda: None)
        lifecycle = captured["lifecycle"](host, runtime)
        self.assertIsInstance(lifecycle, MayaPlaybackLifecycle)
        self.assertIs(lifecycle._timer, timer)

    def test_argumentless_bootstrap_leaves_host_to_resolve_split_maya_modules(self):
        """実MayaではHostがOpenMayaとOpenMayaAnimを別々に解決する。"""

        captured = {}
        open_maya_anim = SimpleNamespace(MAnimControl=_Anim)

        def fake_bootstrap(config, host_factory, lifecycle_factory, connection_factory):
            captured["host"] = host_factory
            return "session"

        with (
            mock.patch.object(maya_session, "_resolve_api", return_value=_BootstrapApi),
            mock.patch.object(maya_session, "bootstrap_playback_session", side_effect=fake_bootstrap),
            mock.patch.object(maya_playback_host, "_OPEN_MAYA", _BootstrapApi),
            mock.patch.object(maya_playback_host, "_OPEN_MAYA_ANIM", open_maya_anim),
        ):
            self.assertEqual("session", bootstrap_maya_playback_session(cmds_module=_Cmds()))
            host = captured["host"](lambda _event: None)

        self.assertIs(_BootstrapApi, host._api)
        self.assertIs(_Anim, host._anim)

    def test_default_bootstrap_rejects_duplicate_host_api_and_time_unit(self):
        for option in ("api", "time_unit"):
            with self.subTest(option=option):
                with self.assertRaisesRegex(PlaybackSessionError, option):
                    bootstrap_maya_playback_session(
                        cmds_module=_Cmds(),
                        api=_BootstrapApi,
                        host_options={option: object()},
                    )

    def test_default_config_fails_closed_for_invalid_mtime_seconds(self):
        for value in (True, 0.0, float("nan"), float("inf"), None):
            with self.subTest(value=value):
                _MTime.seconds = value
                try:
                    with self.assertRaises(PlaybackBootstrapError):
                        default_maya_playback_config(cmds_module=_Cmds(), api=_BootstrapApi)
                finally:
                    _MTime.seconds = 1.0 / 24.0

    def test_explicit_config_must_match_current_maya_timebase(self):
        explicit = default_maya_playback_config(cmds_module=_Cmds(), api=_BootstrapApi)
        with mock.patch.object(maya_session, "bootstrap_playback_session", return_value="session"):
            session = bootstrap_maya_playback_session(
                config=explicit,
                cmds_module=_Cmds(),
                api=_BootstrapApi,
            )
        self.assertEqual("session", session)

        mismatched = replace(explicit, time_unit="ntsc")
        with self.assertRaisesRegex(PlaybackBootstrapError, "time unit"):
            bootstrap_maya_playback_session(config=mismatched, cmds_module=_Cmds(), api=_BootstrapApi)

    def test_time_unit_drift_during_capture_fails_closed(self):
        class DriftingCmds(_Cmds):
            def __init__(self):
                super().__init__()
                self._labels = iter(("film", "ntsc"))

            def currentUnit(self, **kwargs):
                self.calls.append(("currentUnit", kwargs))
                return next(self._labels)

        with self.assertRaisesRegex(PlaybackBootstrapError, "changed during capture"):
            default_maya_playback_config(cmds_module=DriftingCmds(), api=_BootstrapApi)

    def test_rate_approximation_rejects_an_inaccurate_custom_value(self):
        _MTime.seconds = 1.0 / 23.123456
        try:
            with self.assertRaisesRegex(PlaybackBootstrapError, "accurate"):
                default_maya_playback_config(cmds_module=_Cmds(), api=_BootstrapApi)
        finally:
            _MTime.seconds = 1.0 / 24.0


if __name__ == "__main__":
    unittest.main()
