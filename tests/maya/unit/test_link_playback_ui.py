"""Maya Playback Sync menuの状態遷移とreload cleanupを検証する。"""

import sys
import threading
import types
import unittest
from unittest import mock

import ywta.reloadmodules as reloadmodules
import ywta.link.playback_ui as playback_ui


class _Cmds:
    """Playback checkbox用のMaya cmds最小fake。"""

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
            return args[0] if args else "menuItem"
        return "playbackItem"

    def warning(self, message):
        self.warnings.append(message)


class _Session:
    """開始・終了呼び出しを記録するSession fake。"""

    def __init__(self, *, start=True, close=True):
        self.start_result = start
        self.close_result = close
        self.starts = 0
        self.closes = 0

    def start(self):
        self.starts += 1
        if isinstance(self.start_result, BaseException):
            raise self.start_result
        return self.start_result

    def close(self):
        self.closes += 1
        if isinstance(self.close_result, BaseException):
            raise self.close_result
        return self.close_result


class PlaybackUiTests(unittest.TestCase):
    """Mayaを起動せずPlayback Sync UIの契約を確認する。"""

    def setUp(self):
        playback_ui._ACTIVE_SESSION = None
        playback_ui._menu_item = None
        playback_ui._menu_cmds = None
        self.cmds = _Cmds()

    def tearDown(self):
        playback_ui._ACTIVE_SESSION = None
        playback_ui._menu_item = None
        playback_ui._menu_cmds = None

    def test_menu_has_one_link_divider_and_checkbox(self):
        item = playback_ui.create_menu_item("animationMenu", cmds_module=self.cmds)

        self.assertEqual("playbackItem", item)
        self.assertEqual(2, len(self.cmds.calls))
        divider, checkbox = self.cmds.calls
        self.assertEqual("YWTA Link", divider[1]["dividerLabel"])
        self.assertTrue(divider[1]["divider"])
        self.assertEqual("Playback Sync", checkbox[1]["label"])
        self.assertTrue(checkbox[1]["annotation"])
        self.assertIn("frame rate", checkbox[1]["annotation"])
        self.assertEqual("play_regular.png", checkbox[1]["image"])
        self.assertTrue(callable(checkbox[1]["command"]))

    def test_enable_disable_is_idempotent(self):
        session = _Session()
        bootstrap = mock.Mock(return_value=session)

        self.assertTrue(playback_ui.set_enabled(True, bootstrap=bootstrap))
        self.assertTrue(playback_ui.set_enabled(True, bootstrap=bootstrap))
        self.assertTrue(playback_ui.is_enabled())
        self.assertEqual(1, bootstrap.call_count)
        self.assertEqual(1, session.starts)

        self.assertFalse(playback_ui.set_enabled(False, cmds_module=self.cmds))
        self.assertFalse(playback_ui.set_enabled(False, cmds_module=self.cmds))
        self.assertEqual(1, session.closes)
        self.assertFalse(playback_ui.is_enabled())

    def test_start_failure_closes_session_and_does_not_enable(self):
        session = _Session(start=RuntimeError("start failed"))

        with self.assertRaises(playback_ui.PlaybackUiError):
            playback_ui.set_enabled(True, bootstrap=lambda: session)

        self.assertFalse(playback_ui.is_enabled())
        self.assertEqual(1, session.closes)
        self.assertIsNone(playback_ui.active_playback_session())

    def test_start_and_cleanup_failure_retains_checked_session_for_retry(self):
        session = _Session(start=RuntimeError("start failed"), close=RuntimeError("close failed"))
        playback_ui.create_menu_item("animationMenu", cmds_module=self.cmds)
        self.cmds.checkbox = True

        result = playback_ui.menu_callback(object(), bootstrap=lambda: session, cmds_module=self.cmds)

        self.assertTrue(result)
        self.assertTrue(playback_ui.is_enabled())
        self.assertIs(session, playback_ui.active_playback_session())
        self.assertTrue(self.cmds.checkbox)
        self.assertEqual(1, session.closes)
        self.assertEqual(1, len(self.cmds.warnings))

        session.close_result = True
        self.assertFalse(playback_ui.set_enabled(False, cmds_module=self.cmds))
        self.assertIsNone(playback_ui.active_playback_session())

    def test_lifecycle_calls_fail_fast_off_main_thread(self):
        session = _Session()
        bootstrap = mock.Mock(return_value=session)
        errors = []

        def run_from_worker():
            try:
                playback_ui.set_enabled(True, bootstrap=bootstrap)
            except BaseException as error:
                errors.append(error)
            try:
                playback_ui.close()
            except BaseException as error:
                errors.append(error)

        worker = threading.Thread(target=run_from_worker)
        worker.start()
        worker.join()

        self.assertEqual(2, len(errors))
        self.assertTrue(all(isinstance(error, playback_ui.PlaybackUiError) for error in errors))
        bootstrap.assert_not_called()
        self.assertEqual(0, session.closes)

    def test_close_failure_retains_session_for_retry(self):
        session = _Session(close=RuntimeError("close failed"))
        playback_ui.set_enabled(True, bootstrap=lambda: session)

        with self.assertRaises(playback_ui.PlaybackUiError):
            playback_ui.set_enabled(False, cmds_module=self.cmds)
        self.assertTrue(playback_ui.is_enabled())
        self.assertIs(session, playback_ui.active_playback_session())

        session.close_result = True
        self.assertFalse(playback_ui.set_enabled(False, cmds_module=self.cmds))
        self.assertFalse(playback_ui.is_enabled())
        self.assertIsNone(playback_ui.active_playback_session())
        self.assertEqual(2, session.closes)

    def test_callback_restores_checkbox_and_warns_on_failure(self):
        playback_ui.create_menu_item("animationMenu", cmds_module=self.cmds)
        self.cmds.checkbox = True

        with mock.patch.object(playback_ui, "bootstrap_maya_playback_session", side_effect=RuntimeError("start failed")):
            result = playback_ui.menu_callback(object(), cmds_module=self.cmds)

        self.assertFalse(result)
        self.assertFalse(self.cmds.checkbox)
        self.assertEqual(1, len(self.cmds.warnings))
        self.assertIn("Playback Sync", self.cmds.warnings[0])

    def test_reload_closes_playback_before_reloading_modules(self):
        events = []

        def close():
            events.append("close")
            return True

        def reload(module):
            events.append(("reload", module.__name__))
            return module

        with (
            mock.patch.object(playback_ui, "close", side_effect=close),
            mock.patch.object(reloadmodules.importlib, "reload", side_effect=reload),
            mock.patch.object(reloadmodules.ywta, "initialize", side_effect=lambda: events.append("initialize")),
        ):
            reloadmodules.unload_packages(["ywta.link.playback_ui"])

        self.assertEqual("close", events[0])
        self.assertLess(events.index("close"), events.index(("reload", "ywta.link.playback_ui")))
        self.assertEqual("initialize", events[-1])

    def test_rollback_uninstall_closes_playback_before_reloading_modules(self):
        events = []
        module_name = "ywta.test_reload_probe"
        importer = reloadmodules.RollbackImporter()
        sys.modules[module_name] = types.ModuleType(module_name)

        def close():
            events.append("close")
            return True

        def reload(module):
            events.append(("reload", module.__name__))
            return module

        try:
            with (
                mock.patch.object(playback_ui, "close", side_effect=close),
                mock.patch.object(reloadmodules.importlib, "reload", side_effect=reload),
            ):
                importer.uninstall()
        finally:
            sys.modules.pop(module_name, None)

        self.assertEqual("close", events[0])
        self.assertLess(events.index("close"), events.index(("reload", module_name)))

    def test_rollback_uninstall_aborts_when_playback_cleanup_fails(self):
        importer = reloadmodules.RollbackImporter()
        with (
            mock.patch.object(playback_ui, "close", side_effect=RuntimeError("close failed")),
            mock.patch.object(reloadmodules.importlib, "reload") as reload,
        ):
            with self.assertRaises(RuntimeError):
                importer.uninstall()

        reload.assert_not_called()

    def test_reload_aborts_when_playback_cleanup_fails(self):
        with (
            mock.patch.object(playback_ui, "close", side_effect=RuntimeError("close failed")),
            mock.patch.object(reloadmodules.importlib, "reload") as reload,
        ):
            with self.assertRaises(RuntimeError):
                reloadmodules.unload_packages(["ywta.link.playback_ui"])

        reload.assert_not_called()


if __name__ == "__main__":
    unittest.main()
