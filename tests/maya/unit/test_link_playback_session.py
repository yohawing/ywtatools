"""Maya向けPlayback Session compositionを検証する。"""

import unittest

from ywta.link import (
    MayaPlaybackHost,
    MayaPlaybackLifecycle,
    compose_maya_playback_session,
)
from ywta_link import PlaybackSessionConfig, PlaybackSessionError, RationalRate


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

    def isPlaying(self):
        return False


class _Api:
    """Maya API引数の最小fake。"""

    MAnimControl = _Anim


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
        self.events = []

    def join(self, room):
        self.events.append(("join", room))

    def close(self):
        self.events.append(("close",))

    def receive(self, timeout=None):
        raise RuntimeError("not started")

    def publish(self, *args, **kwargs):
        return "message-id"

    def subscribe(self, *args):
        return "subscription-id"

    def unsubscribe(self, *args):
        return None


def _config():
    """テスト用にRoom、Authority、timebaseを明示する。"""

    return PlaybackSessionConfig(
        peer_id="maya:peer-001",
        session_id="session-001",
        room="room-001",
        topic="playback",
        channel_id="playback-main",
        initial_authority="maya:peer-001",
        ticks_per_host_unit=1,
        host_unit_rate=RationalRate(24, 1),
        time_unit="film",
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
            host_options={"api": _Api, "anim_control": _Anim(), "time_unit": "film"},
            lifecycle_options={"timer_interval_ms": 25},
        )

        self.assertIsInstance(session.lifecycle, MayaPlaybackLifecycle)
        self.assertIsInstance(session.lifecycle._host, MayaPlaybackHost)
        self.assertIs(session.lifecycle._timer, timer)
        self.assertEqual(25, timer.interval)
        self.assertEqual([("join", "room-001")], client.events)

        self.assertTrue(session.close())
        self.assertEqual([("join", "room-001"), ("close",)], client.events)
        self.assertFalse(timer.started)

    def test_reserved_options_are_rejected_before_client_creation(self):
        cases = (
            ("on_change", {"host_options": {"on_change": lambda event: None}}),
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


if __name__ == "__main__":
    unittest.main()
