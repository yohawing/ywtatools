"""Maya Camera同期lifecycleの固有契約を検証する。"""

import unittest

from ywta.link.camera_lifecycle import MayaCameraLifecycle


class _Signal:
    def connect(self, callback):
        self.callback = callback


class _Timer:
    def __init__(self):
        self.timeout = _Signal()
        self.stops = 0

    def setInterval(self, _interval):
        pass

    def start(self):
        pass

    def stop(self):
        self.stops += 1


class _Runtime:
    def __init__(self, events):
        self.events = events

    def start(self):
        return True

    def pump(self, *, max_items=None):
        self.events.append(("runtime.pump", max_items))
        return 0

    def close(self):
        return True


class _Host:
    registered = False
    failed = False
    last_error = None

    def __init__(self, events):
        self.events = events
        self.fail_flush = False

    def register(self):
        self.registered = True
        return True

    def unregister(self):
        self.registered = False
        return True

    def quarantine(self):
        self.failed = True
        return True

    def flush(self):
        self.events.append("host.flush")
        if self.fail_flush:
            raise RuntimeError("flush failed")
        return True


class _SceneMessage:
    kMayaExiting = "exit"

    def addCallback(self, _event, _callback):
        return "exit-id"


class _Message:
    def removeCallback(self, _callback_id):
        pass


class MayaCameraLifecycleTests(unittest.TestCase):
    """Playback lifecycleの安全境界を再利用し、Camera固有順序だけ確認する。"""

    def test_timer_flushes_host_before_pumping_runtime(self):
        events = []
        timer = _Timer()
        lifecycle = MayaCameraLifecycle(
            _Runtime(events),
            _Host(events),
            timer=timer,
            scene_message=_SceneMessage(),
            message=_Message(),
            max_pump_items=17,
        )

        self.assertTrue(lifecycle.start())
        timer.timeout.callback()

        self.assertEqual(["host.flush", ("runtime.pump", 17)], events)

    def test_requires_flush_capable_host(self):
        with self.assertRaisesRegex(RuntimeError, "host.flush"):
            MayaCameraLifecycle(
                _Runtime([]),
                object(),
                timer=_Timer(),
                scene_message=_SceneMessage(),
                message=_Message(),
            )

    def test_flush_failure_stops_timer_without_pumping_runtime(self):
        events = []
        timer = _Timer()
        host = _Host(events)
        host.fail_flush = True
        lifecycle = MayaCameraLifecycle(_Runtime(events), host, timer=timer, scene_message=_SceneMessage(), message=_Message())
        lifecycle.start()

        timer.timeout.callback()

        self.assertTrue(lifecycle.failed)
        self.assertEqual(["host.flush"], events)
        self.assertEqual(1, timer.stops)


if __name__ == "__main__":
    unittest.main()
