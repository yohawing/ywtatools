"""Maya向けPlayback Sessionの薄いcomposition wrapper。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable

from ywta_link import PlaybackSession, PlaybackSessionConfig, PlaybackSessionError, compose_playback_session

from .lifecycle import MayaPlaybackLifecycle
from .playback_host import MayaPlaybackHost


_RESERVED_HOST_OPTIONS = frozenset(("on_change",))
_RESERVED_LIFECYCLE_OPTIONS = frozenset(("runtime", "host", "timer", "scene_message", "message"))


def compose_maya_playback_session(
    config: PlaybackSessionConfig,
    *,
    timer: Any = None,
    scene_message: Any = None,
    message: Any = None,
    client_factory: Callable[[PlaybackSessionConfig], Any] | None = None,
    host_options: Mapping[str, Any] | None = None,
    lifecycle_options: Mapping[str, Any] | None = None,
) -> PlaybackSession:
    """Maya HostとLifecycleを共通Playback Sessionへ接続する。

    Room、Authority、timebaseは`config`からのみ受け取る。共通compositionはClientを
    生成し、デフォルトでは`connect_or_start`後にRoomへjoinする。このwrapperはSessionの
    開始は行わず、Maya外のテストでは専用引数と`host_options`で依存を注入できる。
    """

    host_kwargs = _copy_options(host_options, "host_options", _RESERVED_HOST_OPTIONS)
    lifecycle_kwargs = _copy_options(lifecycle_options, "lifecycle_options", _RESERVED_LIFECYCLE_OPTIONS)
    if timer is not None:
        lifecycle_kwargs["timer"] = timer
    if scene_message is not None:
        lifecycle_kwargs["scene_message"] = scene_message
    if message is not None:
        lifecycle_kwargs["message"] = message

    return compose_playback_session(
        config,
        lambda on_change: MayaPlaybackHost(on_change, **host_kwargs),
        lambda host, runtime: MayaPlaybackLifecycle(runtime, host, **lifecycle_kwargs),
        client_factory=client_factory,
    )


def _copy_options(options: Mapping[str, Any] | None, name: str, reserved: frozenset[str]) -> dict[str, Any]:
    """注入専用引数と衝突するoptionをClient生成前に拒否する。"""

    if options is None:
        return {}
    if not isinstance(options, Mapping):
        raise PlaybackSessionError(f"{name} must be a mapping")
    copied = dict(options)
    conflicts = sorted(set(copied).intersection(reserved))
    if conflicts:
        raise PlaybackSessionError(f"{name} contains reserved option: {conflicts[0]}")
    return copied


__all__ = ("compose_maya_playback_session",)
