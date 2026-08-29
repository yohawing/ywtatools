"""Blender向けCamera Sessionの薄い構成wrapper。"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from ywta_link import (
    CameraBootstrapConfig,
    CameraSession,
    CameraSessionConfig,
    CameraSessionError,
    bootstrap_camera_session as _bootstrap_camera_session,
    compose_camera_session as _compose_camera_session,
)

from .link_camera import BlenderCameraHost
from .link_lifecycle import BlenderPlaybackLifecycle
from .link_session import _plugin_version, _resolve_bpy, _version_text


def compose_blender_camera_session(
    config: CameraSessionConfig,
    *,
    bpy_module: Any = None,
    client_factory: Callable[[CameraSessionConfig], object] | None = None,
    host_options: Mapping[str, Any] | None = None,
    lifecycle_options: Mapping[str, Any] | None = None,
) -> CameraSession:
    """Blender Host/Lifecycleを共通Camera Sessionへ組み込む。"""

    factories = _blender_camera_factories(bpy_module, host_options, lifecycle_options)
    return _compose_camera_session(config, *factories, client_factory)


def default_blender_camera_config(*, bpy_module: Any = None) -> CameraBootstrapConfig:
    """Blender application identityから標準Camera bootstrap設定を作る。"""

    bpy = _resolve_bpy(bpy_module)
    return CameraBootstrapConfig(
        application_id="blender",
        application="Blender",
        application_version=_version_text(getattr(getattr(bpy, "app", None), "version", None), "bpy.app.version"),
        plugin_version=_plugin_version(),
    )


def bootstrap_blender_camera_session(
    *,
    config: CameraBootstrapConfig | None = None,
    bpy_module: Any = None,
    connection_factory: Callable[[str, object], object] | None = None,
    host_options: Mapping[str, Any] | None = None,
    lifecycle_options: Mapping[str, Any] | None = None,
) -> CameraSession:
    """共通Camera bootstrapで未開始Sessionを構成する。"""

    if config is not None and not isinstance(config, CameraBootstrapConfig):
        raise CameraSessionError("config must be a CameraBootstrapConfig or None")
    bpy = _resolve_bpy(bpy_module)
    config = config or default_blender_camera_config(bpy_module=bpy)
    factories = _blender_camera_factories(bpy, host_options, lifecycle_options)
    return _bootstrap_camera_session(config, *factories, connection_factory)


def _blender_camera_factories(
    bpy_module: Any,
    host_options: Mapping[str, Any] | None,
    lifecycle_options: Mapping[str, Any] | None,
) -> tuple[Callable[[object], BlenderCameraHost], Callable[[object, object], BlenderPlaybackLifecycle]]:
    """明示composeとdefault bootstrapが共有するfactoryを作る。"""

    host_kwargs = dict(host_options or {})
    lifecycle_kwargs = dict(lifecycle_options or {})
    if "bpy_module" in host_kwargs or "bpy_module" in lifecycle_kwargs:
        raise CameraSessionError("bpy_module must be passed as the dedicated argument")
    host_kwargs["bpy_module"] = bpy_module
    lifecycle_kwargs["bpy_module"] = bpy_module

    def host_factory(on_change: object) -> BlenderCameraHost:
        return BlenderCameraHost(on_change, **host_kwargs)  # type: ignore[arg-type]

    def lifecycle_factory(host: object, runtime: object) -> BlenderPlaybackLifecycle:
        return BlenderPlaybackLifecycle(host, runtime, **lifecycle_kwargs)

    return host_factory, lifecycle_factory


__all__ = (
    "bootstrap_blender_camera_session",
    "compose_blender_camera_session",
    "default_blender_camera_config",
)
