"""Maya Camera Session composition wrapperを検証する。"""

import threading
import unittest
from unittest import mock

from ywta_link import CameraSessionConfig
import ywta.link.camera_session as camera_session


class MayaCameraSessionTests(unittest.TestCase):
    """Maya依存を注入し、HostとLifecycleの配線だけを確認する。"""

    def test_compose_connects_camera_host_and_lifecycle(self):
        config = CameraSessionConfig("maya:1", "session", "room", "camera", "camera", "maya:1")
        captured = {}

        def fake_compose(received, host_factory, lifecycle_factory, client_factory=None):
            captured["config"] = received
            captured["host"] = host_factory("relay")
            captured["lifecycle"] = lifecycle_factory("host", "runtime")
            captured["client_factory"] = client_factory
            return "session"

        host_type = mock.Mock(return_value="maya-host")
        lifecycle_type = mock.Mock(return_value="maya-lifecycle")
        client_factory = object()
        with (
            mock.patch.object(camera_session, "compose_camera_session", side_effect=fake_compose),
            mock.patch.object(camera_session, "MayaCameraHost", host_type),
            mock.patch.object(camera_session, "MayaCameraLifecycle", lifecycle_type),
        ):
            result = camera_session.compose_maya_camera_session(
                config,
                timer="timer",
                scene_message="scene",
                message="message",
                client_factory=client_factory,
                host_options={"aspect_ratio": 1.5},
                lifecycle_options={"timer_interval_ms": 50},
            )

        self.assertEqual("session", result)
        self.assertIs(config, captured["config"])
        self.assertIs(client_factory, captured["client_factory"])
        host_type.assert_called_once_with("relay", aspect_ratio=1.5)
        lifecycle_type.assert_called_once_with(
            "runtime",
            "host",
            timer="timer",
            scene_message="scene",
            message="message",
            timer_interval_ms=50,
        )

    def test_rejects_reserved_options(self):
        config = CameraSessionConfig("maya:1", "session", "room", "camera", "camera", "maya:1")
        for kwargs in (
            {"host_options": {"on_change": object()}},
            {"lifecycle_options": {"runtime": object()}},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(RuntimeError, "reserved option"):
                camera_session.compose_maya_camera_session(config, **kwargs)

    def test_default_config_uses_maya_identity(self):
        cmds = mock.Mock()
        cmds.about.return_value = "2024"

        config = camera_session.default_maya_camera_config(cmds_module=cmds)

        self.assertEqual("maya", config.application_id)
        self.assertEqual("Autodesk Maya", config.application)
        self.assertEqual("2024", config.application_version)

    def test_bootstrap_freezes_host_during_common_composition(self):
        cmds = mock.Mock()
        cmds.about.return_value = "2024"
        host_type = mock.Mock(return_value="host")
        lifecycle_type = mock.Mock(return_value="lifecycle")
        connection = mock.Mock()

        def fake_bootstrap(config, host_factory, lifecycle_factory, connection_factory):
            self.assertEqual("maya", config.application_id)
            self.assertIs(connection, connection_factory)
            self.assertEqual("host", host_factory("relay"))
            self.assertEqual("lifecycle", lifecycle_factory("host", "runtime"))
            return "session"

        with (
            mock.patch.object(camera_session, "bootstrap_camera_session", side_effect=fake_bootstrap),
            mock.patch.object(camera_session, "MayaCameraHost", host_type),
            mock.patch.object(camera_session, "MayaCameraLifecycle", lifecycle_type),
        ):
            result = camera_session.bootstrap_maya_camera_session(
                cmds_module=cmds,
                connection_factory=connection,
                host_options={"aspect_ratio": 1.5},
                lifecycle_options={"on_terminal": "callback"},
            )

        self.assertEqual("session", result)
        host_type.assert_called_once_with("relay", aspect_ratio=1.5)
        lifecycle_type.assert_called_once_with("runtime", "host", on_terminal="callback")

    def test_public_composition_rejects_worker_thread_before_maya_access(self):
        config = CameraSessionConfig("maya:1", "session", "room", "camera", "camera", "maya:1")
        errors = []

        def worker():
            try:
                camera_session.compose_maya_camera_session(config)
            except BaseException as error:
                errors.append(error)

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()

        self.assertEqual(1, len(errors))
        self.assertIsInstance(errors[0], RuntimeError)
        self.assertIn("Main Thread", str(errors[0]))


if __name__ == "__main__":
    unittest.main()
