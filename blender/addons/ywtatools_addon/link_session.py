"""Blender向けPlayback Sessionの薄い構成wrapper。"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from ywta_link import PlaybackSession, PlaybackSessionConfig, PlaybackSessionError, compose_playback_session

from .link_lifecycle import BlenderPlaybackLifecycle
from .link_playback import BlenderPlaybackHost


def compose_blender_playback_session(
    config: PlaybackSessionConfig,
    *,
    bpy_module: Any = None,
    client_factory: Callable[[PlaybackSessionConfig], object] | None = None,
    host_options: Mapping[str, Any] | None = None,
    lifecycle_options: Mapping[str, Any] | None = None,
) -> PlaybackSession:
    """Blender Host/Lifecycleを共通Playback Sessionへ組み込む。

    Room、Authority、timebaseは``config``から明示的に受け取り、Broker接続や
    Session開始は行わない。``bpy_module``は標準Pythonテスト用に注入できる。
    """

    host_kwargs = dict(host_options or {})
    lifecycle_kwargs = dict(lifecycle_options or {})
    if "bpy_module" in host_kwargs or "bpy_module" in lifecycle_kwargs:
        raise PlaybackSessionError("bpy_module must be passed as the dedicated argument")
    host_kwargs.setdefault("bpy_module", bpy_module)
    lifecycle_kwargs.setdefault("bpy_module", bpy_module)

    def host_factory(on_change: object) -> BlenderPlaybackHost:
        return BlenderPlaybackHost(on_change, **host_kwargs)  # type: ignore[arg-type]

    def lifecycle_factory(host: object, runtime: object) -> BlenderPlaybackLifecycle:
        return BlenderPlaybackLifecycle(host, runtime, **lifecycle_kwargs)  # type: ignore[arg-type]

    return compose_playback_session(config, host_factory, lifecycle_factory, client_factory)


__all__ = ("compose_blender_playback_session",)
