"""Maya向けCamera Sessionの薄いcomposition wrapper。"""

from __future__ import annotations

from collections.abc import Mapping
import threading
from typing import Any, Callable

from ywta_link import (
    CameraBootstrapConfig,
    CameraBootstrapError,
    CameraSession,
    CameraSessionConfig,
    CameraSessionError,
    bootstrap_camera_session,
    compose_camera_session,
)

from .. import __version__
from .camera_host import MayaCameraHost
from .camera_lifecycle import MayaCameraLifecycle


_RESERVED_HOST_OPTIONS = frozenset(("on_change",))
_RESERVED_LIFECYCLE_OPTIONS = frozenset(("runtime", "host", "timer", "scene_message", "message"))
_MAYA_CMDS: Any = None


def default_maya_camera_config(*, cmds_module: Any = None) -> CameraBootstrapConfig:
    """Mayaのversion情報からCamera bootstrap設定を作る。"""

    maya_cmds = _resolve_cmds(cmds_module)
    try:
        version = maya_cmds.about(version=True)
    except Exception as error:
        raise CameraBootstrapError("Maya version could not be queried") from error
    if not isinstance(version, str) or not version.strip():
        raise CameraBootstrapError("Maya version must be a non-empty string")
    return CameraBootstrapConfig("maya", "Autodesk Maya", version, __version__)


def bootstrap_maya_camera_session(
    *,
    config: CameraBootstrapConfig | None = None,
    cmds_module: Any = None,
    connection_factory: Callable[[str, Any], object] | None = None,
    host_options: Mapping[str, Any] | None = None,
    lifecycle_options: Mapping[str, Any] | None = None,
) -> CameraSession:
    """active viewport cameraを固定してCamera slotへbootstrapする。"""

    _require_main_thread(CameraBootstrapError)
    resolved_config = default_maya_camera_config(cmds_module=cmds_module) if config is None else config
    host_kwargs = _copy_options(host_options, "host_options", _RESERVED_HOST_OPTIONS)
    lifecycle_kwargs = _copy_options(lifecycle_options, "lifecycle_options", _RESERVED_LIFECYCLE_OPTIONS)
    host_factory, lifecycle_factory = _maya_camera_factories(host_kwargs, lifecycle_kwargs)
    return bootstrap_camera_session(resolved_config, host_factory, lifecycle_factory, connection_factory)


def compose_maya_camera_session(
    config: CameraSessionConfig,
    *,
    timer: Any = None,
    scene_message: Any = None,
    message: Any = None,
    client_factory: Callable[[CameraSessionConfig], Any] | None = None,
    host_options: Mapping[str, Any] | None = None,
    lifecycle_options: Mapping[str, Any] | None = None,
) -> CameraSession:
    """Maya Camera HostとLifecycleを未開始の共通Sessionへ接続する。"""

    _require_main_thread(CameraSessionError)
    host_kwargs = _copy_options(host_options, "host_options", _RESERVED_HOST_OPTIONS)
    lifecycle_kwargs = _copy_options(lifecycle_options, "lifecycle_options", _RESERVED_LIFECYCLE_OPTIONS)
    for name, value in (("timer", timer), ("scene_message", scene_message), ("message", message)):
        if value is not None:
            lifecycle_kwargs[name] = value

    host_factory, lifecycle_factory = _maya_camera_factories(host_kwargs, lifecycle_kwargs)
    return compose_camera_session(config, host_factory, lifecycle_factory, client_factory=client_factory)


def _maya_camera_factories(
    host_options: Mapping[str, Any],
    lifecycle_options: Mapping[str, Any],
) -> tuple[Callable[[Callable[[Any], None]], MayaCameraHost], Callable[[object, object], MayaCameraLifecycle]]:
    """Maya Camera Host/Lifecycle factoryを一度だけ構成する。"""

    host_kwargs = dict(host_options)
    lifecycle_kwargs = dict(lifecycle_options)

    def host_factory(on_change: Callable[[Any], None]) -> MayaCameraHost:
        """生成時のactive viewport cameraを固定する。"""

        return MayaCameraHost(on_change, **host_kwargs)

    def lifecycle_factory(host: object, runtime: object) -> MayaCameraLifecycle:
        """構成済みcomponentをMaya Main Thread lifecycleへ渡す。"""

        return MayaCameraLifecycle(runtime, host, **lifecycle_kwargs)

    return host_factory, lifecycle_factory


def _copy_options(options: Mapping[str, Any] | None, name: str, reserved: frozenset[str]) -> dict[str, Any]:
    """依存注入引数と衝突するoptionを拒否する。"""

    if options is None:
        return {}
    if not isinstance(options, Mapping):
        raise CameraSessionError(f"{name} must be a mapping")
    copied = dict(options)
    conflicts = sorted(set(copied).intersection(reserved))
    if conflicts:
        raise CameraSessionError(f"{name} contains reserved option: {conflicts[0]}")
    return copied


def _resolve_cmds(cmds_module: Any) -> Any:
    """注入されたcmdsまたはMaya cmdsを解決する。"""

    resolved = _MAYA_CMDS if cmds_module is None else cmds_module
    if resolved is None:
        try:
            import maya.cmds as resolved
        except ImportError as error:
            raise CameraBootstrapError("Maya cmds is unavailable; inject cmds_module") from error
    if not callable(getattr(resolved, "about", None)):
        raise CameraBootstrapError("cmds.about is unavailable")
    return resolved


def _require_main_thread(error_type: type[RuntimeError]) -> None:
    """viewport cameraへ触れる公開compositionをMain Threadへ限定する。"""

    if threading.main_thread().ident != threading.get_ident():
        raise error_type("Maya Camera Session must be composed on the Maya Main Thread")


__all__ = (
    "bootstrap_maya_camera_session",
    "compose_maya_camera_session",
    "default_maya_camera_config",
)
