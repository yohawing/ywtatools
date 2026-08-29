"""Blender向けPlayback Sessionの薄い構成wrapper。"""

from __future__ import annotations

import math
from fractions import Fraction
from typing import Any, Callable, Mapping

from ywta_link import (
    PlaybackBootstrapConfig,
    PlaybackSession,
    PlaybackSessionConfig,
    PlaybackSessionError,
    RationalRate,
    bootstrap_playback_session as _bootstrap_playback_session,
    compose_playback_session as _compose_playback_session,
)

from .link_lifecycle import BlenderPlaybackLifecycle
from .link_playback import BlenderPlaybackHost, BlenderPlaybackHostError


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

    host_factory, lifecycle_factory = _blender_factories(
        bpy_module=bpy_module,
        host_options=host_options,
        lifecycle_options=lifecycle_options,
        timebase_rate=None,
    )
    return _compose_playback_session(config, host_factory, lifecycle_factory, client_factory)


def default_blender_playback_config(
    *,
    bpy_module: Any = None,
) -> PlaybackBootstrapConfig:
    """現在のBlender sceneから標準Playback bootstrap設定を作る。

    ``bpy_module``は標準Python単体テストや別のBlender contextから注入できる。
    ``fps``と``fps_base``はsceneの時刻単位であり、再生速度としては扱わない。
    """

    bpy = _resolve_bpy(bpy_module)
    app = getattr(bpy, "app", None)
    version = _version_text(getattr(app, "version", None), "bpy.app.version")
    scene = getattr(getattr(bpy, "context", None), "scene", None)
    render = getattr(scene, "render", None)
    fps = _positive_integer(getattr(render, "fps", None), "scene.render.fps")
    fps_base = _positive_real(getattr(render, "fps_base", None), "scene.render.fps_base")
    host_unit_rate = _scene_rate(fps, fps_base)

    return PlaybackBootstrapConfig(
        application_id="blender",
        application="Blender",
        application_version=version,
        plugin_version=_plugin_version(),
        host_unit_rate=host_unit_rate,
        time_unit="frames",
    )


def bootstrap_blender_playback_session(
    *,
    config: PlaybackBootstrapConfig | None = None,
    bpy_module: Any = None,
    connection_factory: Callable[[str, object], object] | None = None,
    host_options: Mapping[str, Any] | None = None,
    lifecycle_options: Mapping[str, Any] | None = None,
) -> PlaybackSession:
    """現在のBlender sceneで共通Playback bootstrapを実行する。

    Brokerへの接続、slot claim、既存slotのAuthority照合を完了した後、
    Sessionは開始せずに返す。開始と終了はBlender Main ThreadのLifecycleへ委譲する。
    """

    if config is not None and not isinstance(config, PlaybackBootstrapConfig):
        raise PlaybackSessionError("config must be a PlaybackBootstrapConfig or None")
    bpy = _resolve_bpy(bpy_module)
    if config is None:
        config = default_blender_playback_config(bpy_module=bpy)
    else:
        _validate_config_scene(config, bpy)
    host_factory, lifecycle_factory = _blender_factories(
        bpy_module=bpy,
        host_options=host_options,
        lifecycle_options=lifecycle_options,
        timebase_rate=config.host_unit_rate,
    )
    return _bootstrap_playback_session(config, host_factory, lifecycle_factory, connection_factory)


def _blender_factories(
    *,
    bpy_module: Any,
    host_options: Mapping[str, Any] | None,
    lifecycle_options: Mapping[str, Any] | None,
    timebase_rate: RationalRate | None,
) -> tuple[Callable[[object], BlenderPlaybackHost], Callable[[object, object], BlenderPlaybackLifecycle]]:
    """明示composeとdefault bootstrapが共有するHost/Lifecycle factoryを作る。"""

    host_kwargs = dict(host_options or {})
    lifecycle_kwargs = dict(lifecycle_options or {})
    if "bpy_module" in host_kwargs or "bpy_module" in lifecycle_kwargs:
        raise PlaybackSessionError("bpy_module must be passed as the dedicated argument")
    if "timebase_validator" in host_kwargs:
        raise PlaybackSessionError("timebase_validator is reserved by the Blender adapter")
    host_kwargs.setdefault("bpy_module", bpy_module)
    if timebase_rate is not None:
        host_kwargs["timebase_validator"] = _timebase_validator(timebase_rate)
    lifecycle_kwargs.setdefault("bpy_module", bpy_module)

    def host_factory(on_change: object) -> BlenderPlaybackHost:
        return BlenderPlaybackHost(on_change, **host_kwargs)  # type: ignore[arg-type]

    def lifecycle_factory(host: object, runtime: object) -> BlenderPlaybackLifecycle:
        return BlenderPlaybackLifecycle(host, runtime, **lifecycle_kwargs)  # type: ignore[arg-type]

    return host_factory, lifecycle_factory


def _resolve_bpy(bpy_module: Any) -> Any:
    """注入値または実Blenderのbpy moduleを取得する。"""

    if bpy_module is not None:
        return bpy_module
    try:
        import bpy  # type: ignore[import-not-found]
    except ImportError as error:
        raise PlaybackSessionError("Blender Python API is unavailable; inject bpy_module for tests") from error
    return bpy


def _scene_rate(fps: int, fps_base: float | int) -> RationalRate:
    """Blenderのfps/fps_baseを丸めずに共通RationalRateへ変換する。"""

    try:
        rate = Fraction(fps, 1) / Fraction(str(fps_base))
        return RationalRate(rate.numerator, rate.denominator)
    except (ValueError, ZeroDivisionError, TypeError, OverflowError) as error:
        raise PlaybackSessionError(f"invalid Blender scene timebase: {error}") from error


def _validate_config_scene(config: PlaybackBootstrapConfig, bpy: Any) -> None:
    """明示bootstrap設定と現在sceneのtimebaseを照合する。"""

    if config.time_unit != "frames":
        raise PlaybackSessionError("Blender Playback bootstrap requires time_unit='frames'")
    scene = getattr(getattr(bpy, "context", None), "scene", None)
    try:
        _timebase_validator(config.host_unit_rate)(scene)
    except BlenderPlaybackHostError as error:
        raise PlaybackSessionError("configured Playback timebase does not match the Blender scene") from error


def _timebase_validator(expected_rate: RationalRate) -> Callable[[Any], None]:
    """対象sceneのFPSがbootstrap時のrateから変わっていないことを検証する。"""

    def validate(scene: Any) -> None:
        try:
            render = getattr(scene, "render", None)
            fps = _positive_integer(getattr(render, "fps", None), "scene.render.fps")
            fps_base = _positive_real(getattr(render, "fps_base", None), "scene.render.fps_base")
            actual_rate = _scene_rate(fps, fps_base)
        except PlaybackSessionError as error:
            raise BlenderPlaybackHostError(f"invalid Blender scene timebase: {error}") from error
        if actual_rate != expected_rate:
            raise BlenderPlaybackHostError("Blender scene timebase changed after Playback bootstrap")

    return validate


def _positive_integer(value: object, field_name: str) -> int:
    """boolを除く正の整数を検証する。"""

    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PlaybackSessionError(f"{field_name} must be a positive integer")
    return value


def _positive_real(value: object, field_name: str) -> float | int:
    """boolを除く正の有限数を検証する。"""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PlaybackSessionError(f"{field_name} must be a positive finite number")
    if not math.isfinite(float(value)) or value <= 0:
        raise PlaybackSessionError(f"{field_name} must be a positive finite number")
    return value


def _version_text(value: object, field_name: str) -> str:
    """Blender version tupleをドット区切り文字列へ変換する。"""

    if (
        not isinstance(value, (tuple, list))
        or not value
        or any(isinstance(part, bool) or not isinstance(part, int) or part < 0 for part in value)
    ):
        raise PlaybackSessionError(f"{field_name} must be a non-empty integer version tuple")
    return ".".join(str(part) for part in value)


def _plugin_version() -> str:
    """addon packageのbl_info versionを安全に読み取る。"""

    try:
        from . import bl_info
    except (ImportError, AttributeError) as error:
        raise PlaybackSessionError("Blender addon bl_info is unavailable") from error
    if not isinstance(bl_info, Mapping) or "version" not in bl_info:
        raise PlaybackSessionError("Blender addon bl_info.version is unavailable")
    return _version_text(bl_info["version"], "bl_info.version")


__all__ = (
    "bootstrap_blender_playback_session",
    "compose_blender_playback_session",
    "default_blender_playback_config",
)
