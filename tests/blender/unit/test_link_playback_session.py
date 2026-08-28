"""Blender Playback Session wrapperの構成境界を検証する。"""

from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path

from ywta_link import PlaybackSessionConfig, PlaybackSessionError, RationalRate


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


_PLAYBACK_MODULE = _load_module(f"{_PACKAGE}.link_playback")
_LIFECYCLE_MODULE = _load_module(f"{_PACKAGE}.link_lifecycle")
_SESSION_MODULE = _load_module(f"{_PACKAGE}.link_session")
BlenderPlaybackHost = _PLAYBACK_MODULE.BlenderPlaybackHost
BlenderPlaybackLifecycle = _LIFECYCLE_MODULE.BlenderPlaybackLifecycle
compose_blender_playback_session = _SESSION_MODULE.compose_blender_playback_session


class _Timers:
    """Blender timer APIの最小fake。"""


class _Bpy:
    """Host/Lifecycle構成に必要な最小fake bpy。"""

    def __init__(self) -> None:
        self.app = types.SimpleNamespace(timers=_Timers())


class _Client:
    """構成と未開始終了に必要な最小fake Client。"""

    def __init__(self) -> None:
        self.closed = 0

    def join(self, _room: str) -> str:
        return "joined"

    def close(self) -> None:
        self.closed += 1

    def receive(self, timeout: object = None) -> object:
        raise RuntimeError("not started")

    def publish(self, *_args: object, **_kwargs: object) -> str:
        return "message"

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


if __name__ == "__main__":
    unittest.main()
