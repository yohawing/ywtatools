"""Blender Camera Session wrapperの構成境界を検証する。"""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

from ywta_link import CameraBootstrapConfig, CameraSessionConfig, CameraSessionError

_ADDON = Path(__file__).parents[3] / "blender" / "addons" / "ywtatools_addon"
package = sys.modules.get("ywtatools_addon")
if package is None:
    package = types.ModuleType("ywtatools_addon")
    package.__path__ = [str(_ADDON)]
    sys.modules["ywtatools_addon"] = package
package.bl_info = {"version": (0, 0, 1)}


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _ADDON / f"{name.rsplit('.', 1)[-1]}.py")
    if spec is None or spec.loader is None:
        raise ImportError(name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_load("ywtatools_addon.link_playback")
_CAMERA = _load("ywtatools_addon.link_camera")
_LIFECYCLE = _load("ywtatools_addon.link_lifecycle")
_PLAYBACK_SESSION = _load("ywtatools_addon.link_session")
_SESSION = _load("ywtatools_addon.link_camera_session")


class _Vector:
    def __init__(self, *values):
        self.values = values
        if len(values) == 4:
            self.x, self.y, self.z, self.w = values

    def __iter__(self):
        return iter(self.values)


class _Matrix:
    is_negative = False
    has_shear = False

    def decompose(self):
        return _Vector(0.0, 0.0, 0.0), _Vector(0.0, 0.0, 0.0, 1.0), _Vector(1.0, 1.0, 1.0)


class _Client:
    def __init__(self):
        self.peer_id = "blender:peer"
        self.closed = 0

    def join(self, _room):
        return "joined"

    def close(self):
        self.closed += 1

    def receive(self, timeout=None):
        raise RuntimeError("not started")

    def publish(self, *_args, **_kwargs):
        return "message"

    def subscribe(self, *_args, **_kwargs):
        return "subscribed"

    def unsubscribe(self, *_args, **_kwargs):
        return "unsubscribed"

    def request(self, *_args, **kwargs):
        return kwargs.get("message_id", "request")

    def response(self, *_args, **_kwargs):
        return "response"


class _Bpy:
    def __init__(self):
        data = types.SimpleNamespace(
            type="PERSP",
            lens=50.0,
            sensor_width=36.0,
            sensor_height=24.0,
            sensor_fit="AUTO",
            shift_x=0.0,
            shift_y=0.0,
            clip_start=0.1,
            clip_end=1000.0,
            ortho_scale=10.0,
            exposure=0.0,
            dof=types.SimpleNamespace(use_dof=False, focus_distance=10.0, aperture_fstop=2.8),
        )
        camera = types.SimpleNamespace(
            data=data,
            name_full="Camera",
            matrix_world=_Matrix(),
            scale=(1.0, 1.0, 1.0),
            parent=None,
            as_pointer=lambda: 1,
        )
        render = types.SimpleNamespace(
            resolution_x=1920,
            resolution_y=1080,
            pixel_aspect_x=1.0,
            pixel_aspect_y=1.0,
            fps=24,
            fps_base=1.0,
        )
        scene = types.SimpleNamespace(
            camera=camera,
            unit_settings=types.SimpleNamespace(scale_length=1.0),
            render=render,
            frame_current=1,
            frame_subframe=0.0,
        )
        self.context = types.SimpleNamespace(scene=scene)
        self.app = types.SimpleNamespace(
            version=(5, 2, 0),
            handlers=types.SimpleNamespace(depsgraph_update_post=[]),
            timers=types.SimpleNamespace(),
        )


def _config():
    return CameraSessionConfig("blender:peer", "session", "room", "camera", "camera", "blender:peer")


class BlenderCameraSessionTests(unittest.TestCase):
    def test_compose_uses_exact_host_and_shared_lifecycle(self):
        bpy = _Bpy()
        client = _Client()
        session = _SESSION.compose_blender_camera_session(
            _config(),
            bpy_module=bpy,
            client_factory=lambda _config: client,
            host_options={"matrix_compose": lambda *_args: _Matrix()},
            lifecycle_options={"timer_interval": 0.2},
        )
        self.assertIs(type(session.lifecycle._host), _CAMERA.BlenderCameraHost)
        self.assertIs(type(session.lifecycle), _LIFECYCLE.BlenderPlaybackLifecycle)
        self.assertEqual(0.2, session.lifecycle._timer_interval)
        self.assertTrue(session.close())
        self.assertEqual(1, client.closed)

    def test_bpy_module_is_reserved(self):
        for option in ("host_options", "lifecycle_options"):
            with self.subTest(option=option):
                with self.assertRaisesRegex(CameraSessionError, "bpy_module"):
                    _SESSION.compose_blender_camera_session(
                        _config(),
                        bpy_module=_Bpy(),
                        client_factory=lambda _config: _Client(),
                        **{option: {"bpy_module": _Bpy()}},
                    )

    def test_default_config_uses_blender_identity(self):
        config = _SESSION.default_blender_camera_config(bpy_module=_Bpy())
        self.assertIsInstance(config, CameraBootstrapConfig)
        self.assertEqual(
            ("blender", "Blender", "5.2.0", "0.0.1"),
            (
                config.application_id,
                config.application,
                config.application_version,
                config.plugin_version,
            ),
        )

    def test_bootstrap_delegates_to_common_camera_bootstrap(self):
        sentinel = object()

        def connection_factory(*_args):
            return _Client()

        with patch.object(_SESSION, "_bootstrap_camera_session", return_value=sentinel) as bootstrap:
            result = _SESSION.bootstrap_blender_camera_session(
                bpy_module=_Bpy(),
                connection_factory=connection_factory,
                lifecycle_options={"timer_interval": 0.2},
            )
        self.assertIs(result, sentinel)
        config, host_factory, lifecycle_factory, passed_connection = bootstrap.call_args.args
        self.assertIsInstance(config, CameraBootstrapConfig)
        self.assertIs(passed_connection, connection_factory)
        host = host_factory(lambda _camera: True)
        runtime = types.SimpleNamespace(start=lambda: True, pump=lambda **_kwargs: 0, close=lambda: True)
        lifecycle = lifecycle_factory(host, runtime)
        self.assertIs(type(host), _CAMERA.BlenderCameraHost)
        self.assertIs(type(lifecycle), _LIFECYCLE.BlenderPlaybackLifecycle)

    def test_public_api_keeps_common_bootstrap_options_in_config(self):
        self.assertEqual(tuple(inspect.signature(_SESSION.default_blender_camera_config).parameters), ("bpy_module",))
        self.assertEqual(
            tuple(inspect.signature(_SESSION.bootstrap_blender_camera_session).parameters),
            ("config", "bpy_module", "connection_factory", "host_options", "lifecycle_options"),
        )


if __name__ == "__main__":
    unittest.main()
