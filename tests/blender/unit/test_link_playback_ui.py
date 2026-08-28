"""Blender外からPlayback Sync UIの状態境界を検証する。"""

from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path


_ROOT = Path(__file__).parents[3]
_ADDON = _ROOT / "blender" / "addons" / "ywtatools_addon"
_PACKAGE = "ywtatools_addon"


class _FakeLayout:
    """Panel drawのprop呼び出しだけを記録するfake。"""

    def __init__(self) -> None:
        self.calls: list[tuple[object, str]] = []

    def prop(self, owner: object, name: str) -> None:
        self.calls.append((owner, name))


class _FakeSession:
    """Playback Session lifecycleの最小fake。"""

    def __init__(self) -> None:
        self.started = False
        self.closed = False
        self.fail_start = False
        self.fail_close = False
        self.close_result = True
        self.start_calls = 0
        self.close_calls = 0

    def start(self) -> bool:
        self.start_calls += 1
        if self.fail_start:
            raise RuntimeError("start failed")
        self.started = True
        return True

    def close(self) -> bool:
        self.close_calls += 1
        if self.fail_close:
            raise RuntimeError("close failed")
        if self.close_result is not True:
            return self.close_result
        self.started = False
        self.closed = True
        return True


class _StatusSession:
    """Lifecycle statusのactive判定を検証するfake。"""

    def __init__(self, **status: object) -> None:
        self.lifecycle = types.SimpleNamespace(status=types.SimpleNamespace(**status))


class _OuterSessionState:
    """外側SessionとLifecycleの終了状態が異なるfake。"""

    def __init__(self) -> None:
        self._closed = False
        self.lifecycle = types.SimpleNamespace(
            status=types.SimpleNamespace(
                started=False,
                closed=True,
                failed=True,
                timer_registered=False,
            )
        )
        self.close_calls = 0

    def close(self) -> bool:
        self.close_calls += 1
        self._closed = True
        return True


class LinkPlaybackUITests(unittest.TestCase):
    """checkboxがSession実状態だけを所有することを検証する。"""

    @classmethod
    def setUpClass(cls) -> None:
        fake_bpy = types.ModuleType("bpy")
        fake_props = types.ModuleType("bpy.props")
        fake_types = types.ModuleType("bpy.types")
        fake_bpy.types = fake_types
        fake_bpy.props = fake_props
        fake_bpy.utils = types.SimpleNamespace(
            register_class=cls._register_class,
            unregister_class=cls._unregister_class,
        )
        fake_types.WindowManager = type("WindowManager", (), {})
        fake_types.Panel = type("Panel", (), {})

        def bool_property(**kwargs: object) -> dict[str, object]:
            return kwargs

        fake_props.BoolProperty = bool_property
        cls._registered_classes: list[type] = []
        cls._fake_bpy = fake_bpy
        old_bpy = sys.modules.get("bpy")
        old_props = sys.modules.get("bpy.props")
        old_types = sys.modules.get("bpy.types")
        sys.modules["bpy"] = fake_bpy
        sys.modules["bpy.props"] = fake_props
        sys.modules["bpy.types"] = fake_types
        try:
            package = sys.modules.get(_PACKAGE)
            if package is None:
                package = types.ModuleType(_PACKAGE)
                package.__path__ = [str(_ADDON)]
                sys.modules[_PACKAGE] = package
            elif not hasattr(package, "__path__"):
                package.__path__ = [str(_ADDON)]
            name = f"{_PACKAGE}.link_ui_test_instance"
            spec = importlib.util.spec_from_file_location(name, _ADDON / "link_ui.py")
            if spec is None or spec.loader is None:
                raise ImportError("cannot load link_ui")
            cls.module = importlib.util.module_from_spec(spec)
            sys.modules[name] = cls.module
            spec.loader.exec_module(cls.module)
        finally:
            _restore_module("bpy", old_bpy)
            _restore_module("bpy.props", old_props)
            _restore_module("bpy.types", old_types)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.module._ACTIVE_SESSION = None
        sys.modules.pop(f"{_PACKAGE}.link_ui_test_instance", None)

    @staticmethod
    def _register_class(cls: type) -> None:
        LinkPlaybackUITests._registered_classes.append(cls)

    @staticmethod
    def _unregister_class(cls: type) -> None:
        LinkPlaybackUITests._registered_classes.remove(cls)

    def setUp(self) -> None:
        self.module._ACTIVE_SESSION = None
        self.module._PROPERTY_REGISTERED = False
        self.module._PANEL_REGISTERED = False
        self._old_bootstrap = self.module._bootstrap_session
        self._register_ui()

    def tearDown(self) -> None:
        self.module._bootstrap_session = self._old_bootstrap
        self.module._ACTIVE_SESSION = None
        if hasattr(self._fake_bpy.types.WindowManager, self.module.PLAYBACK_SYNC_PROPERTY):
            delattr(self._fake_bpy.types.WindowManager, self.module.PLAYBACK_SYNC_PROPERTY)
        self.module._PROPERTY_REGISTERED = False
        self.module._PANEL_REGISTERED = False
        self._registered_classes.clear()

    def _register_ui(self) -> None:
        self.module.register()

    def test_panel_draws_exactly_one_playback_property_without_poll(self) -> None:
        panel = self.module.YWTA_PT_Link()
        panel.layout = _FakeLayout()
        window_manager = object()
        panel.draw(types.SimpleNamespace(window_manager=window_manager))

        self.assertFalse(hasattr(self.module.YWTA_PT_Link, "poll"))
        self.assertEqual([(window_manager, "ywta_playback_sync")], panel.layout.calls)

    def test_property_has_skip_save_and_japanese_description(self) -> None:
        spec = getattr(self._fake_bpy.types.WindowManager, "ywta_playback_sync")

        self.assertEqual({"SKIP_SAVE"}, spec["options"])
        self.assertEqual("Playback Sync", spec["name"])
        self.assertRegex(spec["description"], "[ぁ-んァ-ン一-龯]")
        self.assertIs(spec["get"], self.module._get_playback_sync)
        self.assertIs(spec["set"], self.module._set_playback_sync)

    def test_enable_requires_successful_start_and_is_idempotent(self) -> None:
        session = _FakeSession()
        self.module._bootstrap_session = lambda: session

        self.module._set_playback_sync(object(), True)
        self.assertIs(session, self.module.active_playback_session())
        self.assertTrue(self.module._get_playback_sync(object()))
        self.module._set_playback_sync(object(), True)
        self.assertEqual(1, session.start_calls)

    def test_start_failure_closes_session_and_stays_inactive(self) -> None:
        session = _FakeSession()
        session.fail_start = True
        self.module._bootstrap_session = lambda: session

        self.module._set_playback_sync(object(), True)

        self.assertEqual(1, session.close_calls)
        self.assertIsNone(self.module.active_playback_session())
        self.assertFalse(self.module._get_playback_sync(object()))

    def test_start_failure_cleanup_failure_retains_session_for_retry(self) -> None:
        session = _FakeSession()
        session.fail_start = True
        session.fail_close = True
        self.module._bootstrap_session = lambda: session

        self.module._set_playback_sync(object(), True)

        self.assertIs(session, self.module.active_playback_session())
        self.assertFalse(self.module._get_playback_sync(object()))
        self.assertEqual(1, session.close_calls)

    def test_start_failure_cleanup_false_retains_session_for_retry(self) -> None:
        session = _FakeSession()
        session.fail_start = True
        session.close_result = False
        self.module._bootstrap_session = lambda: session

        self.module._set_playback_sync(object(), True)

        self.assertIs(session, self.module.active_playback_session())
        self.assertFalse(self.module._get_playback_sync(object()))
        self.assertEqual(1, session.close_calls)

    def test_on_retries_nonactive_nonclosed_session_before_fresh_bootstrap(self) -> None:
        retained = _FakeSession()
        retained.started = False
        fresh = _FakeSession()
        self.module._ACTIVE_SESSION = retained
        bootstrap = iter((fresh,))
        self.module._bootstrap_session = lambda: next(bootstrap)

        self.module._set_playback_sync(object(), True)

        self.assertEqual(1, retained.close_calls)
        self.assertIs(fresh, self.module.active_playback_session())
        self.assertEqual(1, fresh.start_calls)

    def test_failed_lifecycle_status_is_not_active(self) -> None:
        for status in (
            {"started": False, "closed": False, "failed": False, "timer_registered": True},
            {"started": True, "closed": True, "failed": False, "timer_registered": True},
            {"started": True, "closed": False, "failed": True, "timer_registered": True},
            {"started": True, "closed": False, "failed": False, "timer_registered": False},
        ):
            with self.subTest(status=status):
                self.module._ACTIVE_SESSION = _StatusSession(**status)
                self.assertFalse(self.module._get_playback_sync(object()))

        self.module._ACTIVE_SESSION = _StatusSession(
            started=True,
            closed=False,
            failed=False,
            timer_registered=True,
        )
        self.assertTrue(self.module._get_playback_sync(object()))

    def test_outer_session_state_controls_close_retry(self) -> None:
        session = _OuterSessionState()
        self.module._ACTIVE_SESSION = session

        self.module._set_playback_sync(object(), False)

        self.assertEqual(1, session.close_calls)
        self.assertIsNone(self.module.active_playback_session())

    def test_outer_session_state_is_used_for_on_recovery(self) -> None:
        retained = _OuterSessionState()
        fresh = _FakeSession()
        self.module._ACTIVE_SESSION = retained
        self.module._bootstrap_session = lambda: fresh

        self.module._set_playback_sync(object(), True)

        self.assertEqual(1, retained.close_calls)
        self.assertIs(fresh, self.module.active_playback_session())

    def test_unregister_retries_outer_session_close_before_removing_ui(self) -> None:
        session = _OuterSessionState()
        self.module._ACTIVE_SESSION = session

        self.module.unregister()

        self.assertEqual(1, session.close_calls)
        self.assertFalse(self.module._PANEL_REGISTERED)
        self.assertFalse(hasattr(self._fake_bpy.types.WindowManager, "ywta_playback_sync"))

    def test_close_failure_retains_active_session_for_retry(self) -> None:
        session = _FakeSession()
        session.started = True
        session.fail_close = True
        self.module._ACTIVE_SESSION = session

        self.module._set_playback_sync(object(), False)
        self.assertIs(session, self.module.active_playback_session())
        self.assertTrue(self.module._get_playback_sync(object()))

        session.fail_close = False
        self.module._set_playback_sync(object(), False)
        self.assertIsNone(self.module.active_playback_session())
        self.assertEqual(2, session.close_calls)

    def test_unregister_closes_before_property_delete_and_retries_failed_close(self) -> None:
        session = _FakeSession()
        session.started = True
        session.fail_close = True
        self.module._ACTIVE_SESSION = session

        with self.assertRaises(self.module.LinkUIError):
            self.module.unregister()
        self.assertTrue(hasattr(self._fake_bpy.types.WindowManager, "ywta_playback_sync"))
        self.assertTrue(self.module._PANEL_REGISTERED)
        self.assertIn(self.module.YWTA_PT_Link, self._registered_classes)

        session.fail_close = False
        self.module.unregister()
        self.assertFalse(hasattr(self._fake_bpy.types.WindowManager, "ywta_playback_sync"))
        self.assertFalse(self.module._PANEL_REGISTERED)
        self.assertEqual(2, session.close_calls)


def _restore_module(name: str, module: types.ModuleType | None) -> None:
    """テスト用fake moduleを元のsys.modulesへ戻す。"""

    if module is None:
        sys.modules.pop(name, None)
    else:
        sys.modules[name] = module


if __name__ == "__main__":
    unittest.main()
