"""Blender playback lifecycleのtimer・rollback境界を検証する。"""

from __future__ import annotations

import importlib.util
import sys
import threading
import types
import unittest
from pathlib import Path


_ROOT = Path(__file__).parents[3]
_ADDON = _ROOT / "blender" / "addons" / "ywtatools_addon"
_PACKAGE = "ywtatools_addon"
if _PACKAGE not in sys.modules:
    package = types.ModuleType(_PACKAGE)
    package.__path__ = [str(_ADDON)]
    sys.modules[_PACKAGE] = package


def _load_module(name: str):
    """addon moduleをBlender外からロードする。"""

    spec = importlib.util.spec_from_file_location(name, _ADDON / f"{name.rsplit('.', 1)[-1]}.py")
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_HOST_MODULE = _load_module(f"{_PACKAGE}.link_playback")
_MODULE = _load_module(f"{_PACKAGE}.link_lifecycle")
BlenderPlaybackLifecycle = _MODULE.BlenderPlaybackLifecycle
BlenderPlaybackLifecycleError = _MODULE.BlenderPlaybackLifecycleError


class _Timers:
    """Blender timer APIの最小fake。"""

    def __init__(self) -> None:
        self.callbacks: list[tuple[object, float, bool]] = []
        self.fail_unregister = False
        self.is_registered_calls = 0

    def register(self, callback, first_interval, persistent=False):
        self.callbacks.append((callback, first_interval, persistent))

    def unregister(self, callback):
        if self.fail_unregister:
            raise RuntimeError("timer unregister failed")
        self.callbacks = [entry for entry in self.callbacks if entry[0] is not callback]

    def is_registered(self, callback):
        self.is_registered_calls += 1
        return any(entry[0] is callback for entry in self.callbacks)


class _Bpy:
    """timerだけを公開するfake bpy。"""

    def __init__(self) -> None:
        self.app = types.SimpleNamespace(timers=_Timers())


class _Host:
    """Host lifecycleの呼び出し順を記録するfake。"""

    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.registered = False
        self.fail_register = False
        self.fail_unregister = False

    def register(self) -> bool:
        self.calls.append("host.register")
        if self.fail_register:
            raise RuntimeError("host register failed")
        self.registered = True
        return True

    def unregister(self) -> bool:
        self.calls.append("host.unregister")
        if self.fail_unregister:
            raise RuntimeError("host unregister failed")
        self.registered = False
        return True


class _Runtime:
    """Runtime lifecycleの呼び出し順を記録するfake。"""

    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.started = False
        self.closed = False
        self.fail_start = False
        self.fail_close = False
        self.fail_pump = False

    @property
    def status(self):
        return types.SimpleNamespace(started=self.started, closed=self.closed)

    def start(self) -> bool:
        self.calls.append("runtime.start")
        if self.fail_start:
            raise RuntimeError("runtime start failed")
        self.started = True
        return True

    def pump(self, *, max_items=None) -> int:
        self.calls.append("runtime.pump")
        if self.fail_pump:
            raise RuntimeError("pump failed")
        return 0

    def close(self) -> bool:
        self.calls.append("runtime.close")
        if self.fail_close:
            raise RuntimeError("runtime close failed")
        self.closed = True
        return True


class BlenderPlaybackLifecycleTests(unittest.TestCase):
    """既存Host/RuntimeのMain Thread lifecycle契約を検証する。"""

    def setUp(self) -> None:
        self.calls: list[str] = []
        self.bpy = _Bpy()
        self.host = _Host(self.calls)
        self.runtime = _Runtime(self.calls)
        self.lifecycle = BlenderPlaybackLifecycle(
            self.host,
            self.runtime,
            bpy_module=self.bpy,
            timer_interval=0.25,
            max_pump_items=8,
        )

    def test_start_and_close_order_are_idempotent(self) -> None:
        """startとcloseは順序を守り、再呼び出しで重複しない。"""

        self.assertTrue(self.lifecycle.start())
        self.assertFalse(self.lifecycle.start())
        self.assertEqual(
            ["runtime.start", "host.register"],
            self.calls,
        )
        self.assertEqual(1, len(self.bpy.app.timers.callbacks))
        callback, interval, persistent = self.bpy.app.timers.callbacks[0]
        self.assertEqual(0.25, interval)
        self.assertTrue(persistent)
        self.assertEqual(0.25, callback())
        self.assertEqual(["runtime.start", "host.register", "runtime.pump"], self.calls)

        self.assertTrue(self.lifecycle.close())
        self.assertFalse(self.lifecycle.close())
        self.assertEqual(
            ["runtime.start", "host.register", "runtime.pump", "host.unregister", "runtime.close"],
            self.calls,
        )
        self.assertEqual([], self.bpy.app.timers.callbacks)
        self.assertTrue(self.lifecycle.closed)

    def test_timer_exception_stops_callback_and_is_recorded(self) -> None:
        """pump例外はevent loopへ漏れず、timerを停止してstatusへ残す。"""

        self.runtime.fail_pump = True
        self.lifecycle.start()
        callback = self.bpy.app.timers.callbacks[0][0]
        self.assertIsNone(callback())
        self.assertFalse(self.lifecycle.timer_registered)
        self.assertTrue(self.lifecycle.failed)
        self.assertEqual("pump", self.lifecycle.last_error.callback)
        self.assertEqual("RuntimeError", self.lifecycle.last_error.exception_type)
        self.assertEqual([], self.bpy.app.timers.callbacks)

        self.assertTrue(self.lifecycle.close())
        self.assertEqual(["runtime.start", "host.register", "runtime.pump", "host.unregister", "runtime.close"], self.calls)

    def test_timer_unregistration_failure_keeps_actual_ledger_for_retry(self) -> None:
        """timer解除失敗時は後続componentを閉じず、次回closeで再試行する。"""

        self.lifecycle.start()
        self.bpy.app.timers.fail_unregister = True
        with self.assertRaises(BlenderPlaybackLifecycleError):
            self.lifecycle.close()
        self.assertTrue(self.lifecycle.timer_registered)
        self.assertTrue(self.host.registered)
        self.assertFalse(self.runtime.closed)
        self.assertEqual(["runtime.start", "host.register"], self.calls)

        self.bpy.app.timers.fail_unregister = False
        self.assertTrue(self.lifecycle.close())
        self.assertEqual(["runtime.start", "host.register", "host.unregister", "runtime.close"], self.calls)

    def test_timer_register_failure_before_insertion_rolls_back(self) -> None:
        """callback挿入前のtimer失敗をfalseと観測し、Host/Runtimeを戻す。"""

        original_register = self.bpy.app.timers.register

        def fail_register(*_args, **_kwargs):
            raise RuntimeError("timer register failed")

        self.bpy.app.timers.register = fail_register
        with self.assertRaises(BlenderPlaybackLifecycleError):
            self.lifecycle.start()
        self.assertEqual(
            ["runtime.start", "host.register", "host.unregister", "runtime.close"],
            self.calls,
        )
        self.assertEqual(1, self.bpy.app.timers.is_registered_calls)
        self.assertTrue(self.lifecycle.closed)
        self.assertFalse(self.lifecycle.timer_registered)
        self.bpy.app.timers.register = original_register

    def test_operations_are_owner_thread_only(self) -> None:
        """生成元thread以外からstart/closeできない。"""

        errors: list[BaseException] = []

        def call_start() -> None:
            try:
                self.lifecycle.start()
            except BaseException as error:
                errors.append(error)

        thread = threading.Thread(target=call_start)
        thread.start()
        thread.join()
        self.assertEqual(1, len(errors))
        self.assertIsInstance(errors[0], BlenderPlaybackLifecycleError)


if __name__ == "__main__":
    unittest.main()
