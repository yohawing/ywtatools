"""Maya Camera Sync checkboxとcleanup契約を検証する。"""

import threading
import types
import unittest
from unittest import mock

import ywta.reloadmodules as reloadmodules
import ywta.link.camera_ui as camera_ui


class _Cmds:
    def __init__(self):
        self.checkbox = False
        self.calls = []
        self.warnings = []

    def menuItem(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if kwargs.get("query"):
            return self.checkbox
        if kwargs.get("edit"):
            self.checkbox = kwargs["checkBox"]
            return args[0]
        return "cameraItem"

    def warning(self, message):
        self.warnings.append(message)


class _Session:
    def __init__(self, *, start=True, close=True, failed=False):
        self.start_result = start
        self.close_result = close
        self.starts = 0
        self.closes = 0
        self.lifecycle = types.SimpleNamespace(status=types.SimpleNamespace(failed=failed, closed=False))

    def start(self):
        self.starts += 1
        if isinstance(self.start_result, BaseException):
            raise self.start_result
        return self.start_result

    def close(self):
        self.closes += 1
        if isinstance(self.close_result, BaseException):
            raise self.close_result
        if self.close_result is True:
            self.lifecycle.status.closed = True
        return self.close_result


class MayaCameraUiTests(unittest.TestCase):
    """Maya外で単一checkboxの状態遷移を確認する。"""

    def setUp(self):
        camera_ui._ACTIVE_SESSION = None
        camera_ui._ACTIVE_STARTED = False
        camera_ui._menu_item = None
        camera_ui._menu_cmds = None
        self.cmds = _Cmds()

    def tearDown(self):
        camera_ui._ACTIVE_SESSION = None
        camera_ui._ACTIVE_STARTED = False
        camera_ui._menu_item = None
        camera_ui._menu_cmds = None

    def test_menu_exposes_one_camera_checkbox_without_extra_status_ui(self):
        self.assertEqual("cameraItem", camera_ui.create_menu_item("animation", cmds_module=self.cmds))

        self.assertEqual(1, len(self.cmds.calls))
        options = self.cmds.calls[0][1]
        self.assertEqual("Camera Sync", options["label"])
        self.assertFalse(options["checkBox"])
        self.assertTrue(callable(options["command"]))

    def test_enable_disable_is_idempotent_and_retains_failed_close(self):
        session = _Session(close=RuntimeError("busy"))
        bootstrap = mock.Mock(return_value=session)

        self.assertTrue(camera_ui.set_enabled(True, bootstrap=bootstrap))
        self.assertTrue(camera_ui.set_enabled(True, bootstrap=bootstrap))
        with self.assertRaises(camera_ui.CameraUiError):
            camera_ui.set_enabled(False)
        self.assertIs(session, camera_ui.active_camera_session())

        session.close_result = True
        self.assertFalse(camera_ui.set_enabled(False))
        self.assertIsNone(camera_ui.active_camera_session())
        self.assertEqual(2, session.closes)

    def test_callback_returns_checkbox_to_off_and_warns_when_start_fails(self):
        camera_ui.create_menu_item("animation", cmds_module=self.cmds)
        self.cmds.checkbox = True

        result = camera_ui.menu_callback(
            True,
            bootstrap=lambda: _Session(start=RuntimeError("start failed")),
            cmds_module=self.cmds,
        )

        self.assertFalse(result)
        self.assertFalse(self.cmds.checkbox)
        self.assertEqual(1, len(self.cmds.warnings))
        self.assertIn("Camera Sync", self.cmds.warnings[0])

    def test_start_and_cleanup_failure_stays_off_but_retains_retry_reference(self):
        camera_ui.create_menu_item("animation", cmds_module=self.cmds)
        session = _Session(start=RuntimeError("start"), close=RuntimeError("close"))

        result = camera_ui.menu_callback(True, bootstrap=lambda: session, cmds_module=self.cmds)

        self.assertFalse(result)
        self.assertFalse(self.cmds.checkbox)
        self.assertIs(session, camera_ui.active_camera_session())
        session.close_result = True
        self.assertFalse(camera_ui.set_enabled(False))
        self.assertIsNone(camera_ui.active_camera_session())

    def test_start_failure_and_incomplete_cleanup_retains_retry_reference(self):
        session = _Session(start=RuntimeError("start"), close=False)

        with self.assertRaisesRegex(camera_ui.CameraUiError, "cleanup did not complete"):
            camera_ui.set_enabled(True, bootstrap=lambda: session)

        self.assertFalse(camera_ui.is_enabled())
        self.assertIs(session, camera_ui.active_camera_session())
        session.close_result = True
        self.assertFalse(camera_ui.set_enabled(False))

    def test_default_bootstrap_refreshes_terminal_state(self):
        with mock.patch.object(
            camera_ui.camera_session,
            "bootstrap_maya_camera_session",
            return_value="session",
            create=True,
        ) as bootstrap:
            self.assertEqual("session", camera_ui._bootstrap_session())

        self.assertIs(camera_ui._refresh_menu_state, bootstrap.call_args.kwargs["lifecycle_options"]["on_terminal"])

    def test_ui_operations_are_main_thread_only(self):
        errors = []

        def worker():
            try:
                camera_ui.set_enabled(True, bootstrap=lambda: _Session())
            except BaseException as error:
                errors.append(error)

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()

        self.assertEqual(1, len(errors))
        self.assertIsInstance(errors[0], camera_ui.CameraUiError)

    def test_reload_closes_camera_before_reloading_modules(self):
        events = []

        def reload(module):
            events.append(("reload", module.__name__))
            return module

        with (
            mock.patch.object(camera_ui, "close", side_effect=lambda: events.append("camera.close")),
            mock.patch.object(reloadmodules.importlib, "reload", side_effect=reload),
            mock.patch.object(reloadmodules.ywta, "initialize"),
        ):
            reloadmodules.unload_packages(["ywta.link.camera_ui"])

        self.assertLess(events.index("camera.close"), events.index(("reload", "ywta.link.camera_ui")))


if __name__ == "__main__":
    unittest.main()
