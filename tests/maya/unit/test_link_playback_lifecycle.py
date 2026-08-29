"""Maya Playback同期SessionのMain Thread lifecycleを検証する。"""

import threading
import unittest

from ywta.link.lifecycle import (
    MayaPlaybackLifecycle,
    MayaPlaybackLifecycleError,
)


class _Signal:
    """QTimer.timeoutの最小signal fake。"""

    def __init__(self):
        self.callback = None

    def connect(self, callback):
        self.callback = callback

    def emit(self):
        if self.callback is not None:
            self.callback()


class _Timer:
    """QTimerの注入境界を記録するfake。"""

    def __init__(self, events):
        self.events = events
        self.timeout = _Signal()
        self.interval = None
        self.running = False
        self.fail_stop = False

    def setInterval(self, interval):
        self.interval = interval

    def start(self):
        self.events.append("timer.start")
        self.running = True

    def stop(self):
        self.events.append("timer.stop")
        if self.fail_stop:
            raise RuntimeError("timer stop failed")
        self.running = False


class _Runtime:
    """PlaybackSyncRuntimeの最小fake。"""

    def __init__(self, events):
        self.events = events
        self.fail_start = False
        self.fail_pump = False
        self.fail_close = False
        self.pump_limits = []

    def start(self):
        self.events.append("runtime.start")
        if self.fail_start:
            raise RuntimeError("runtime start failed")
        return True

    def pump(self, max_items=None):
        self.events.append("runtime.pump")
        self.pump_limits.append(max_items)
        if self.fail_pump:
            raise RuntimeError("pump failed")
        return 0

    def close(self):
        self.events.append("runtime.close")
        if self.fail_close:
            raise RuntimeError("runtime close failed")
        return True


class _Host:
    """MayaPlaybackHostの最小fake。"""

    def __init__(self, events):
        self.events = events
        self.registered = False
        self.failed = False
        self.last_error = None
        self.fail_register = False
        self.fail_unregister = False

    def register(self):
        self.events.append("host.register")
        if self.fail_register:
            raise RuntimeError("host register failed")
        self.registered = True
        return True

    def unregister(self):
        self.events.append("host.unregister")
        if self.fail_unregister:
            raise RuntimeError("host unregister failed")
        self.registered = False
        return True

    def quarantine(self):
        """callback解除前にlocal publishを停止する。"""

        was_failed = self.failed
        self.failed = True
        return not was_failed

    def emit_local(self):
        """登録中のcallbackだけがlocal publishへ到達することを再現する。"""

        if self.registered and not self.failed:
            self.events.append("host.local_publish")


class _SceneMessage:
    """MSceneMessage.addCallbackの最小fake。"""

    kMayaExiting = "mayaExiting"

    def __init__(self, events):
        self.events = events
        self.callback = None
        self.fail_add = False

    def addCallback(self, event, callback):
        self.events.append(("scene.add", event))
        if self.fail_add:
            raise RuntimeError("callback add failed")
        self.callback = callback
        return "exit-id"


class _Message:
    """MMessage.removeCallbackの最小fake。"""

    def __init__(self, events):
        self.events = events
        self.fail_remove = True

    def removeCallback(self, callback_id):
        self.events.append(("message.remove", callback_id))
        if self.fail_remove:
            raise RuntimeError("callback remove failed")


class MayaPlaybackLifecycleTests(unittest.TestCase):
    """MayaとQtをimportしない依存注入テスト。"""

    def setUp(self):
        self.events = []
        self.runtime = _Runtime(self.events)
        self.host = _Host(self.events)
        self.timer = _Timer(self.events)
        self.scene = _SceneMessage(self.events)
        self.message = _Message(self.events)
        self.lifecycle = MayaPlaybackLifecycle(
            self.runtime,
            self.host,
            timer=self.timer,
            scene_message=self.scene,
            message=self.message,
            timer_interval_ms=37,
        )

    def test_start_and_close_are_ordered_and_idempotent(self):
        self.assertTrue(self.lifecycle.start())
        self.assertFalse(self.lifecycle.start())
        self.assertEqual(
            [
                "runtime.start",
                "host.register",
                "timer.start",
                ("scene.add", "mayaExiting"),
            ],
            self.events,
        )
        self.assertEqual(37, self.timer.interval)
        self.assertEqual("exit-id", self.lifecycle.exit_callback_id)

        self.message.fail_remove = False
        self.assertTrue(self.lifecycle.close())
        self.assertFalse(self.lifecycle.close())
        self.assertEqual(
            [
                "runtime.start",
                "host.register",
                "timer.start",
                ("scene.add", "mayaExiting"),
                "timer.stop",
                "host.unregister",
                "runtime.close",
                ("message.remove", "exit-id"),
            ],
            self.events,
        )
        self.assertTrue(self.lifecycle.status.closed)

    def test_status_reflects_terminal_host_failure(self):
        host_error = object()
        self.host.failed = True
        self.host.last_error = host_error

        self.assertTrue(self.lifecycle.status.failed)
        self.assertIs(host_error, self.lifecycle.status.error)

    def test_start_failure_rolls_back_in_reverse_order(self):
        self.scene.fail_add = True
        with self.assertRaises(MayaPlaybackLifecycleError):
            self.lifecycle.start()
        self.assertEqual(
            [
                "runtime.start",
                "host.register",
                "timer.start",
                ("scene.add", "mayaExiting"),
                "timer.stop",
                "host.unregister",
                "runtime.close",
            ],
            self.events,
        )
        self.assertTrue(self.lifecycle.status.closed)
        self.assertTrue(self.lifecycle.status.failed)
        self.assertEqual((), self.lifecycle.callback_ids)

    def test_runtime_start_failure_does_not_close_unstarted_runtime(self):
        self.runtime.fail_start = True
        with self.assertRaises(MayaPlaybackLifecycleError):
            self.lifecycle.start()
        self.assertEqual(["runtime.start"], self.events)
        self.assertTrue(self.lifecycle.status.closed)

    def test_close_retains_failed_callback_removal_for_retry(self):
        self.lifecycle.start()
        with self.assertRaises(MayaPlaybackLifecycleError):
            self.lifecycle.close()
        self.assertEqual(("exit-id",), self.lifecycle.callback_ids)
        self.assertFalse(self.lifecycle.status.closed)

        self.message.fail_remove = False
        self.assertTrue(self.lifecycle.close())
        self.assertEqual(
            [
                "runtime.start",
                "host.register",
                "timer.start",
                ("scene.add", "mayaExiting"),
                "timer.stop",
                "host.unregister",
                "runtime.close",
                ("message.remove", "exit-id"),
                ("message.remove", "exit-id"),
            ],
            self.events,
        )

    def test_timer_error_is_isolated_and_stops_timer(self):
        self.lifecycle.start()
        self.runtime.fail_pump = True
        self.timer.timeout.emit()
        self.timer.timeout.emit()
        self.assertFalse(self.lifecycle.status.timer_running)
        self.assertEqual([64], self.runtime.pump_limits)
        self.assertEqual("timer", self.lifecycle.last_error.callback)
        self.assertEqual("RuntimeError", self.lifecycle.last_error.exception_type)
        self.assertEqual(1, self.lifecycle.last_error.count)
        self.assertFalse(self.host.registered)
        self.host.failed = True
        self.host.last_error = object()
        self.assertTrue(self.lifecycle.status.failed)
        self.assertIs(self.lifecycle.last_error, self.lifecycle.status.error)

    def test_terminal_failure_notifies_once_on_timer_thread(self):
        """非同期終端失敗はtimer処理中に一度だけ通知する。"""

        notifications = []
        lifecycle = MayaPlaybackLifecycle(
            self.runtime,
            self.host,
            timer=self.timer,
            scene_message=self.scene,
            message=self.message,
            on_terminal=lambda: notifications.append(threading.get_ident()),
        )
        lifecycle.start()
        self.runtime.fail_pump = True

        self.timer.timeout.emit()
        self.timer.timeout.emit()

        self.assertEqual([threading.get_ident()], notifications)

    def test_terminal_notification_failure_is_isolated(self):
        """UI通知失敗はtimer callback外へ伝播させない。"""

        def fail_notification():
            raise RuntimeError("refresh failed")

        lifecycle = MayaPlaybackLifecycle(
            self.runtime,
            self.host,
            timer=self.timer,
            scene_message=self.scene,
            message=self.message,
            on_terminal=fail_notification,
        )
        lifecycle.start()
        self.runtime.fail_pump = True

        self.timer.timeout.emit()

        self.assertEqual("timer", lifecycle.last_error.callback)
        self.assertTrue(lifecycle.status.failed)

    def test_host_failure_stops_timer_without_pumping_runtime(self):
        self.lifecycle.start()
        self.host.failed = True

        self.timer.timeout.emit()

        self.assertFalse(self.lifecycle.status.timer_running)
        self.assertFalse(self.host.registered)
        self.assertEqual([], self.runtime.pump_limits)
        self.assertIn("timer.stop", self.events)
        self.assertIn("host.unregister", self.events)

        self.host.emit_local()
        self.assertNotIn("host.local_publish", self.events)

    def test_pump_failure_quarantines_publish_before_unregister_retry(self):
        """callback解除失敗中もlocal publishを止め、closeで解除を再試行する。"""

        self.lifecycle.start()
        self.runtime.fail_pump = True
        self.host.fail_unregister = True

        self.timer.timeout.emit()

        self.assertTrue(self.host.failed)
        self.assertTrue(self.host.registered)
        self.assertTrue(self.lifecycle._host_registered)
        self.host.emit_local()
        self.assertNotIn("host.local_publish", self.events)
        self.host.fail_unregister = False
        self.message.fail_remove = False
        self.assertTrue(self.lifecycle.close())
        self.assertFalse(self.host.registered)

    def test_pre_registered_host_is_not_taken_over(self):
        self.host.registered = True
        with self.assertRaises(MayaPlaybackLifecycleError):
            self.lifecycle.start()
        self.assertEqual([], self.events)
        self.assertTrue(self.host.registered)

    def test_timer_stop_failure_keeps_callbacks_and_runtime_for_retry(self):
        self.lifecycle.start()
        self.timer.fail_stop = True
        with self.assertRaises(MayaPlaybackLifecycleError):
            self.lifecycle.close()
        self.assertTrue(self.lifecycle.status.timer_running)
        self.assertTrue(self.host.registered)
        self.assertEqual(("exit-id",), self.lifecycle.callback_ids)
        self.assertNotIn("runtime.close", self.events)

        self.timer.fail_stop = False
        self.message.fail_remove = False
        self.assertTrue(self.lifecycle.close())

    def test_host_unregister_failure_keeps_exit_callback_and_runtime_for_retry(self):
        self.lifecycle.start()
        self.message.fail_remove = False
        self.host.fail_unregister = True
        with self.assertRaises(MayaPlaybackLifecycleError):
            self.lifecycle.close()
        self.assertTrue(self.host.registered)
        self.assertEqual(("exit-id",), self.lifecycle.callback_ids)
        self.assertNotIn("runtime.close", self.events)

        self.host.fail_unregister = False
        self.assertTrue(self.lifecycle.close())

    def test_runtime_close_failure_keeps_exit_callback_for_retry(self):
        self.lifecycle.start()
        self.message.fail_remove = False
        self.runtime.fail_close = True
        with self.assertRaises(MayaPlaybackLifecycleError):
            self.lifecycle.close()
        self.assertEqual(("exit-id",), self.lifecycle.callback_ids)
        self.assertNotIn(("message.remove", "exit-id"), self.events)

        self.runtime.fail_close = False
        self.assertTrue(self.lifecycle.close())
        self.assertEqual(
            [
                "runtime.start",
                "host.register",
                "timer.start",
                ("scene.add", "mayaExiting"),
                "timer.stop",
                "host.unregister",
                "runtime.close",
                "runtime.close",
                ("message.remove", "exit-id"),
            ],
            self.events,
        )

    def test_maya_exiting_callback_closes_session(self):
        self.lifecycle.start()
        self.message.fail_remove = False
        self.scene.callback()
        self.assertTrue(self.lifecycle.status.closed)

    def test_owner_thread_is_required(self):
        errors = []

        def close_from_worker():
            try:
                self.lifecycle.close()
            except BaseException as error:
                errors.append(error)

        self.lifecycle.start()
        thread = threading.Thread(target=close_from_worker)
        thread.start()
        thread.join()
        self.assertEqual(1, len(errors))
        self.assertIsInstance(errors[0], MayaPlaybackLifecycleError)
        self.assertIn("Main Thread", str(errors[0]))


if __name__ == "__main__":
    unittest.main()
