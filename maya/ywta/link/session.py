"""Maya向けPlayback Sessionの薄いcomposition wrapper。"""

from __future__ import annotations

from collections.abc import Mapping
from fractions import Fraction
import math
from typing import Any, Callable

from ywta_link import (
    PlaybackBootstrapConfig,
    PlaybackBootstrapError,
    PlaybackSession,
    PlaybackSessionConfig,
    PlaybackSessionError,
    RationalRate,
    bootstrap_playback_session,
    compose_playback_session,
)

from .. import __version__
from .lifecycle import MayaPlaybackLifecycle
from .playback_host import MayaPlaybackHost


_RESERVED_HOST_OPTIONS = frozenset(("on_change", "time_unit", "time_unit_label"))
_DEFAULT_RESERVED_HOST_OPTIONS = frozenset(("api", "on_change", "time_unit", "time_unit_label", "time_unit_label_provider"))
_RESERVED_LIFECYCLE_OPTIONS = frozenset(("runtime", "host", "timer", "scene_message", "message"))
_MAYA_CMDS: Any = None
_UNSET = object()


def default_maya_playback_config(
    *,
    cmds_module: Any = None,
    api: Any = None,
) -> PlaybackBootstrapConfig:
    """Mayaの現在設定から共通Playback bootstrap設定を作る。

    ``cmds_module``と``api``は標準Pythonテストから注入できる。
    time unitとrateはMayaから読み取り、呼び出し側の上書きを許可しない。
    """

    maya_cmds = _resolve_cmds(cmds_module)
    maya_api = _resolve_api(api)
    time_unit_label, _time_unit, host_unit_rate = _capture_maya_timebase(maya_cmds, maya_api)
    return _config_from_capture(maya_cmds, time_unit_label, host_unit_rate)


def bootstrap_maya_playback_session(
    *,
    config: PlaybackBootstrapConfig | None = None,
    cmds_module: Any = None,
    api: Any = None,
    timer: Any = None,
    scene_message: Any = None,
    message: Any = None,
    connection_factory: Callable[[str, Any], object] | None = None,
    host_options: Mapping[str, Any] | None = None,
    lifecycle_options: Mapping[str, Any] | None = None,
) -> PlaybackSession:
    """Mayaの現在設定でPlayback Sessionをbootstrapし、未開始Sessionを返す。

    UIからは引数なしで利用でき、標準PythonテストではMaya API、Client、Timerを注入できる。
    Sessionの開始は呼び出し側へ委譲する。
    """

    maya_cmds = _resolve_cmds(cmds_module)
    resolved_api = _resolve_api(api)
    time_unit_label, time_unit, host_unit_rate = _capture_maya_timebase(maya_cmds, resolved_api)
    if config is None:
        config = _config_from_capture(maya_cmds, time_unit_label, host_unit_rate)
    else:
        _validate_explicit_config(config, time_unit_label, host_unit_rate)
    host_kwargs = _copy_options(host_options, "host_options", _DEFAULT_RESERVED_HOST_OPTIONS)
    lifecycle_kwargs = _copy_options(lifecycle_options, "lifecycle_options", _RESERVED_LIFECYCLE_OPTIONS)
    if timer is not None:
        lifecycle_kwargs["timer"] = timer
    if scene_message is not None:
        lifecycle_kwargs["scene_message"] = scene_message
    if message is not None:
        lifecycle_kwargs["message"] = message

    host_factory, lifecycle_factory = _maya_factories(
        host_kwargs,
        lifecycle_kwargs,
        api=resolved_api,
        time_unit=time_unit,
        time_unit_label=time_unit_label,
        time_unit_label_provider=lambda: _current_time_unit_label(maya_cmds),
    )

    return bootstrap_playback_session(config, host_factory, lifecycle_factory, connection_factory)


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

    host_factory, lifecycle_factory = _maya_factories(
        host_kwargs,
        lifecycle_kwargs,
        time_unit_label=config.time_unit,
    )
    return compose_playback_session(config, host_factory, lifecycle_factory, client_factory=client_factory)


def _maya_factories(
    host_kwargs: Mapping[str, Any],
    lifecycle_kwargs: Mapping[str, Any],
    *,
    api: Any = _UNSET,
    time_unit: Any = _UNSET,
    time_unit_label: Any = _UNSET,
    time_unit_label_provider: Any = _UNSET,
) -> tuple[Callable[[Callable[[Any], None]], MayaPlaybackHost], Callable[[object, object], MayaPlaybackLifecycle]]:
    """Maya Host/Lifecycleの共通factoryを構成する。"""

    host_options = dict(host_kwargs)
    if api is not _UNSET:
        host_options["api"] = api
    if time_unit is not _UNSET:
        host_options["time_unit"] = time_unit
    if time_unit_label is not _UNSET:
        host_options["time_unit_label"] = time_unit_label
    if time_unit_label_provider is not _UNSET:
        host_options["time_unit_label_provider"] = time_unit_label_provider
    lifecycle_options = dict(lifecycle_kwargs)

    def host_factory(on_change: Callable[[Any], None]) -> MayaPlaybackHost:
        """Maya Hostを構成する。"""

        return MayaPlaybackHost(on_change, **host_options)

    def lifecycle_factory(host: object, runtime: object) -> MayaPlaybackLifecycle:
        """既存のMaya Lifecycleへ構成済みcomponentを渡す。"""

        return MayaPlaybackLifecycle(runtime, host, **lifecycle_options)

    return host_factory, lifecycle_factory


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


def _resolve_cmds(cmds_module: Any) -> Any:
    """注入されたcmds module、またはMayaのcmds moduleを解決する。"""

    resolved = cmds_module
    if resolved is None:
        resolved = _MAYA_CMDS
    if resolved is None:
        try:
            import maya.cmds as resolved
        except ImportError as error:
            raise PlaybackBootstrapError("Maya cmds is unavailable; inject cmds_module") from error
    if not callable(getattr(resolved, "currentUnit", None)) or not callable(getattr(resolved, "about", None)):
        raise PlaybackBootstrapError("cmds must provide currentUnit() and about()")
    return resolved


def _resolve_api(api: Any) -> Any:
    """注入されたOpenMaya API、またはMayaのOpenMaya moduleを解決する。"""

    if api is not None:
        return api
    try:
        import maya.api.OpenMaya as resolved
    except ImportError as error:
        raise PlaybackBootstrapError("Maya OpenMaya API is unavailable; inject api") from error
    return resolved


def _capture_maya_timebase(cmds_module: Any, api: Any) -> tuple[str, Any, RationalRate]:
    """Mayaのlabel、UI enum、rateを同じ時刻単位からcaptureする。"""

    try:
        label_before = cmds_module.currentUnit(q=True, time=True)
    except Exception as error:
        raise PlaybackBootstrapError(f"Maya time unit could not be queried: {_error_text(error)}") from error
    _require_text(label_before, "time_unit")
    time_unit = _maya_time_unit_enum(api)
    host_unit_rate = _maya_host_unit_rate(api, time_unit)
    try:
        label_after = cmds_module.currentUnit(q=True, time=True)
    except Exception as error:
        raise PlaybackBootstrapError(f"Maya time unit could not be queried: {_error_text(error)}") from error
    _require_text(label_after, "time_unit")
    if label_before != label_after:
        raise PlaybackBootstrapError("Maya time unit changed during capture")
    return label_before, time_unit, host_unit_rate


def _maya_time_unit_enum(api: Any) -> Any:
    """MTime.uiUnit()から現在のMaya UI unit enumを取得する。"""

    mtime_type = getattr(api, "MTime", None)
    if mtime_type is None:
        raise PlaybackBootstrapError("MTime is unavailable")
    ui_unit = getattr(mtime_type, "uiUnit", None)
    if callable(ui_unit):
        try:
            ui_unit = ui_unit()
        except Exception as error:
            raise PlaybackBootstrapError(f"MTime.uiUnit() failed: {_error_text(error)}") from error
    if ui_unit is None:
        raise PlaybackBootstrapError("MTime.uiUnit is unavailable")
    return ui_unit


def _maya_host_unit_rate(api: Any, time_unit: Any) -> RationalRate:
    """Maya MTimeの1 UI unit秒数からhost rateを厳密に作る。"""

    mtime_type = getattr(api, "MTime", None)
    if mtime_type is None:
        raise PlaybackBootstrapError("MTime is unavailable")
    k_seconds = getattr(mtime_type, "kSeconds", None)
    if k_seconds is None:
        raise PlaybackBootstrapError("MTime.kSeconds is unavailable")
    try:
        mtime = mtime_type(1, time_unit)
        as_units = getattr(mtime, "asUnits", None)
        if not callable(as_units):
            raise PlaybackBootstrapError("MTime.asUnits is unavailable")
        seconds = as_units(k_seconds)
    except PlaybackBootstrapError:
        raise
    except Exception as error:
        raise PlaybackBootstrapError(f"MTime conversion failed: {_error_text(error)}") from error
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        raise PlaybackBootstrapError("MTime seconds must be a number")
    seconds_value = float(seconds)
    if not math.isfinite(seconds_value) or seconds_value <= 0:
        raise PlaybackBootstrapError("MTime seconds must be positive and finite")
    try:
        inverse = Fraction(1.0 / seconds_value).limit_denominator(1001)
    except (OverflowError, ZeroDivisionError, ValueError) as error:
        raise PlaybackBootstrapError(f"invalid Maya host unit rate: {_error_text(error)}") from error
    if inverse.numerator <= 0 or inverse.denominator <= 0:
        raise PlaybackBootstrapError("Maya host unit rate must be positive")
    reconstructed_seconds = inverse.denominator / inverse.numerator
    if not math.isclose(reconstructed_seconds, seconds_value, rel_tol=1e-12, abs_tol=1e-15):
        raise PlaybackBootstrapError("Maya host unit rate approximation is not accurate enough")
    try:
        return RationalRate(inverse.numerator, inverse.denominator)
    except (TypeError, ValueError) as error:
        raise PlaybackBootstrapError(f"invalid Maya host unit rate: {_error_text(error)}") from error


def _require_text(value: Any, name: str) -> None:
    """Maya query結果が空でない文字列であることを検証する。"""

    if not isinstance(value, str) or not value.strip():
        raise PlaybackBootstrapError(f"{name} must be a non-empty string")


def _config_from_capture(cmds_module: Any, time_unit_label: str, host_unit_rate: RationalRate) -> PlaybackBootstrapConfig:
    """capture済みのMaya情報からdefault設定を構成する。"""

    try:
        application_version = cmds_module.about(version=True)
    except Exception as error:
        raise PlaybackBootstrapError(f"Maya version could not be queried: {_error_text(error)}") from error
    _require_text(application_version, "application_version")
    return PlaybackBootstrapConfig(
        application_id="maya",
        application="Autodesk Maya",
        application_version=application_version,
        plugin_version=__version__,
        host_unit_rate=host_unit_rate,
        time_unit=time_unit_label,
    )


def _validate_explicit_config(
    config: PlaybackBootstrapConfig,
    time_unit_label: str,
    host_unit_rate: RationalRate,
) -> None:
    """明示設定のtime unitが現在のMaya captureと一致することを検証する。"""

    if not isinstance(config, PlaybackBootstrapConfig):
        raise PlaybackBootstrapError("config must be a PlaybackBootstrapConfig")
    if config.time_unit != time_unit_label:
        raise PlaybackBootstrapError("config.time_unit does not match current Maya time unit")
    if config.host_unit_rate != host_unit_rate:
        raise PlaybackBootstrapError("config.host_unit_rate does not match current Maya timebase")


def _current_time_unit_label(cmds_module: Any) -> str:
    """Mayaの現在time unit labelを取得する。"""

    try:
        value = cmds_module.currentUnit(q=True, time=True)
    except Exception as error:
        raise PlaybackBootstrapError(f"Maya time unit could not be queried: {_error_text(error)}") from error
    _require_text(value, "time_unit")
    return value


def _error_text(error: BaseException) -> str:
    """例外を短い公開messageへ変換する。"""

    try:
        return f"{type(error).__name__}: {str(error)[:1024]}"
    except Exception:
        return f"{type(error).__name__}: <unprintable exception>"


__all__ = (
    "bootstrap_maya_playback_session",
    "compose_maya_playback_session",
    "default_maya_playback_config",
)
