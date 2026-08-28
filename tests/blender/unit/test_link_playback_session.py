"""Blender Playback Session wrapperの構成境界を検証する。"""

from __future__ import annotations

import importlib.util
import inspect
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from ywta_link import PlaybackSessionConfig, PlaybackSessionError, RationalRate


_ROOT = Path(__file__).parents[3]
_ADDON = _ROOT / "blender" / "addons" / "ywtatools_addon"
_PACKAGE = "ywtatools_addon"
package = sys.modules.get(_PACKAGE)
if package is None:
    package = types.ModuleType(_PACKAGE)
    package.__path__ = [str(_ADDON)]
    sys.modules[_PACKAGE] = package
elif not hasattr(package, "__path__"):
    package.__path__ = [str(_ADDON)]
if not hasattr(package, "bl_info"):
    package.bl_info = {"version": (0, 0, 1)}


def _load_module(name: str):
    """addon moduleをBlender外からロードする。"""

    spec = importlib.util.spec_from_file_location(name, _ADDON / f"{name.rsplit('.', 1)[-1]}.py")
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_PLAYBACK_MODULE = _load_module(f"{_PACKAGE}.link_playback")
_LIFECYCLE_MODULE = _load_module(f"{_PACKAGE}.link_lifecycle")
_SESSION_MODULE = _load_module(f"{_PACKAGE}.link_session")
BlenderPlaybackHost = _PLAYBACK_MODULE.BlenderPlaybackHost
BlenderPlaybackHostError = _PLAYBACK_MODULE.BlenderPlaybackHostError
BlenderPlaybackLifecycle = _LIFECYCLE_MODULE.BlenderPlaybackLifecycle
PlaybackBootstrapConfig = _SESSION_MODULE.PlaybackBootstrapConfig
bootstrap_blender_playback_session = _SESSION_MODULE.bootstrap_blender_playback_session
compose_blender_playback_session = _SESSION_MODULE.compose_blender_playback_session
default_blender_playback_config = _SESSION_MODULE.default_blender_playback_config


class _Timers:
    """Blender timer APIの最小fake。"""


class _Bpy:
    """Host/Lifecycle構成に必要な最小fake bpy。"""

    def __init__(self, *, fps: object = 24, fps_base: object = 1.0, version: object = (4, 4, 0)) -> None:
        self.app = types.SimpleNamespace(timers=_Timers(), version=version)
        scene = types.SimpleNamespace(
            frame_current=1,
            frame_start=1,
            frame_end=24,
            frame_step=1,
            frame_subframe=0.0,
            use_preview_range=False,
            frame_preview_start=1,
            frame_preview_end=24,
            render=types.SimpleNamespace(fps=fps, fps_base=fps_base),
        )
        screen = types.SimpleNamespace(is_animation_playing=False)
        self.context = types.SimpleNamespace(scene=scene, screen=screen)


class _Client:
    """構成と未開始終了に必要な最小fake Client。"""

    def __init__(self) -> None:
        self.peer_id = "blender:peer-001"
        self.closed = 0

    def join(self, _room: str) -> str:
        return "joined"

    def close(self) -> None:
        self.closed += 1

    def receive(self, timeout: object = None) -> object:
        raise RuntimeError("not started")

    def publish(self, *_args: object, **_kwargs: object) -> str:
        return "message"

    def request(self, *_args: object, **kwargs: object) -> str:
        return kwargs.get("message_id", "request")  # type: ignore[return-value]

    def response(self, *_args: object, **_kwargs: object) -> str:
        return "response"

    def subscribe(self, *_args: object, **_kwargs: object) -> str:
        return "subscribed"

    def unsubscribe(self, *_args: object, **_kwargs: object) -> str:
        return "unsubscribed"


def _config() -> PlaybackSessionConfig:
    """テスト用の明示的なPlayback設定を返す。"""

    return PlaybackSessionConfig(
        peer_id="blender:peer-001",
        session_id="session-001",
        room="room-001",
        topic="playback",
        channel_id="playback-main",
        initial_authority="blender:peer-001",
        ticks_per_host_unit=1,
        host_unit_rate=RationalRate(24, 1),
        time_unit="frames",
    )


class BlenderPlaybackSessionTests(unittest.TestCase):
    """wrapperがBlender専用componentだけを構成することを検証する。"""

    def test_composes_exact_blender_host_and_lifecycle(self) -> None:
        bpy = _Bpy()
        client = _Client()
        session = compose_blender_playback_session(
            _config(),
            bpy_module=bpy,
            client_factory=lambda _config: client,
            host_options={"timer_interval": 0.2},
            lifecycle_options={"timer_interval": 0.3, "max_pump_items": 4},
        )

        self.assertIs(type(session.lifecycle), BlenderPlaybackLifecycle)
        self.assertIs(type(session.lifecycle._host), BlenderPlaybackHost)
        self.assertIs(session.lifecycle._host._bpy, bpy)
        self.assertEqual(session.lifecycle._host._timer_interval, 0.2)
        self.assertEqual(session.lifecycle._timer_interval, 0.3)
        self.assertEqual(session.lifecycle._max_pump_items, 4)
        session.close()

    def test_close_before_start_closes_dedicated_client(self) -> None:
        client = _Client()
        session = compose_blender_playback_session(
            _config(),
            bpy_module=_Bpy(),
            client_factory=lambda _config: client,
        )

        self.assertTrue(session.close())
        self.assertEqual(client.closed, 1)
        self.assertFalse(session.close())

    def test_bpy_module_is_reserved_to_the_dedicated_argument(self) -> None:
        bpy = _Bpy()
        for option_name in ("host_options", "lifecycle_options"):
            with self.subTest(option_name=option_name):
                with self.assertRaisesRegex(PlaybackSessionError, "dedicated argument"):
                    compose_blender_playback_session(
                        _config(),
                        bpy_module=bpy,
                        client_factory=lambda _config: _Client(),
                        **{option_name: {"bpy_module": _Bpy()}},
                    )

    def test_timebase_validator_is_reserved_to_bootstrap(self) -> None:
        with self.assertRaisesRegex(PlaybackSessionError, "timebase_validator"):
            compose_blender_playback_session(
                _config(),
                bpy_module=_Bpy(),
                client_factory=lambda _config: _Client(),
                host_options={"timebase_validator": lambda _scene: None},
            )

    def test_default_config_uses_blender_identity_and_integer_frame_rate(self) -> None:
        config = default_blender_playback_config(bpy_module=_Bpy())

        self.assertIsInstance(config, PlaybackBootstrapConfig)
        self.assertEqual(config.application_id, "blender")
        self.assertEqual(config.application, "Blender")
        self.assertEqual(config.application_version, "4.4.0")
        self.assertEqual(config.plugin_version, "0.0.1")
        self.assertEqual(config.time_unit, "frames")
        self.assertEqual(config.host_unit_rate, RationalRate(24, 1))
        self.assertEqual(config.ticks_per_host_unit, 5000)

    def test_default_config_preserves_ntsc_rate_without_float_rounding(self) -> None:
        config = default_blender_playback_config(bpy_module=_Bpy(fps=24, fps_base=1.001))

        self.assertEqual(config.host_unit_rate, RationalRate(24000, 1001))
        self.assertEqual(config.ticks_per_host_unit, 5005)

    def test_default_bootstrap_reuses_blender_factories_and_stays_unstarted(self) -> None:
        bpy = _Bpy()

        def connection_factory(_peer_id: str, _presence: object) -> _Client:
            return _Client()

        sentinel = object()

        with patch.object(_SESSION_MODULE, "_bootstrap_playback_session", return_value=sentinel) as bootstrap:
            result = bootstrap_blender_playback_session(
                bpy_module=bpy,
                connection_factory=connection_factory,
                host_options={"timer_interval": 0.2},
                lifecycle_options={"timer_interval": 0.3},
            )

        self.assertIs(result, sentinel)
        config, host_factory, lifecycle_factory, passed_factory = bootstrap.call_args.args
        self.assertIsInstance(config, PlaybackBootstrapConfig)
        self.assertIs(passed_factory, connection_factory)
        host = host_factory(lambda _event: True)
        runtime = types.SimpleNamespace(
            start=lambda: True,
            pump=lambda **_kwargs: 0,
            close=lambda: None,
            status=types.SimpleNamespace(started=False, closed=True),
        )
        lifecycle = lifecycle_factory(host, runtime)
        self.assertIs(type(host), BlenderPlaybackHost)
        self.assertIs(type(lifecycle), BlenderPlaybackLifecycle)
        self.assertEqual(host._timer_interval, 0.2)
        self.assertEqual(lifecycle._timer_interval, 0.3)
        self.assertFalse(lifecycle.started)
        self.assertEqual(host.snapshot().time_unit, config.time_unit)
        bpy.context.scene.render.fps = 30
        with self.assertRaises(BlenderPlaybackHostError):
            host.snapshot()

    def test_default_public_api_does_not_duplicate_bootstrap_options(self) -> None:
        config_parameters = inspect.signature(default_blender_playback_config).parameters
        bootstrap_parameters = inspect.signature(bootstrap_blender_playback_session).parameters

        self.assertEqual(tuple(config_parameters), ("bpy_module",))
        self.assertEqual(
            tuple(bootstrap_parameters),
            ("config", "bpy_module", "connection_factory", "host_options", "lifecycle_options"),
        )

    def test_explicit_bootstrap_rejects_scene_timebase_mismatch(self) -> None:
        config = default_blender_playback_config(bpy_module=_Bpy())
        bpy = _Bpy(fps=30)

        with patch.object(_SESSION_MODULE, "_bootstrap_playback_session") as bootstrap:
            with self.assertRaises(PlaybackSessionError):
                bootstrap_blender_playback_session(config=config, bpy_module=bpy)
        bootstrap.assert_not_called()

    def test_missing_addon_metadata_fails_closed(self) -> None:
        package = sys.modules[_PACKAGE]
        original = package.bl_info
        try:
            package.bl_info = None
            with self.assertRaises(PlaybackSessionError):
                default_blender_playback_config(bpy_module=_Bpy())
        finally:
            package.bl_info = original

    def test_default_config_fails_closed_for_invalid_scene_timebase(self) -> None:
        invalid_values = (
            {"fps": True},
            {"fps": 0},
            {"fps_base": 0.0},
            {"fps_base": float("inf")},
        )
        for values in invalid_values:
            with self.subTest(values=values):
                with self.assertRaises(PlaybackSessionError):
                    default_blender_playback_config(bpy_module=_Bpy(**values))

    def test_default_config_requires_blender_version(self) -> None:
        bpy = _Bpy(version=None)

        with self.assertRaisesRegex(PlaybackSessionError, "bpy.app.version"):
            default_blender_playback_config(bpy_module=bpy)


if __name__ == "__main__":
    unittest.main()
