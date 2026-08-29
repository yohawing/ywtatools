"""Maya Animation menu向けCamera Syncの最小UI境界。"""

from __future__ import annotations

import threading
from typing import Any, Callable

from . import camera_session

try:
    import maya.cmds as _MAYA_CMDS
except ImportError:  # Maya外の標準Pythonでは依存注入を使う。
    _MAYA_CMDS = None


CAMERA_MENU_LABEL = "Camera Sync"
CAMERA_MENU_ANNOTATION = "現在のviewport cameraを固定し、他DCCと同期します"


class CameraUiError(RuntimeError):
    """Camera Sync menuの状態遷移またはcleanup失敗を表す。"""


_ACTIVE_SESSION: Any | None = None
_ACTIVE_STARTED = False
_menu_item: Any | None = None
_menu_cmds: Any | None = None


def is_enabled() -> bool:
    """Camera Syncが正常に有効かを返す。"""

    return _ACTIVE_STARTED and _ACTIVE_SESSION is not None and not _session_terminal(_ACTIVE_SESSION)


def active_camera_session() -> Any | None:
    """moduleが所有するCamera Sessionを返す。"""

    return _ACTIVE_SESSION


def _bootstrap_session() -> Any:
    """active viewport cameraを固定するdefault bootstrapを遅延実行する。"""

    return camera_session.bootstrap_maya_camera_session(lifecycle_options={"on_terminal": _refresh_menu_state})


def set_enabled(enabled: bool, *, bootstrap: Callable[[], Any] | None = None) -> bool:
    """Camera Sessionを開始または終了する。"""

    if not isinstance(enabled, bool):
        raise CameraUiError("enabled must be a bool")
    _require_main_thread("set_enabled")
    if enabled:
        if _ACTIVE_SESSION is not None:
            if is_enabled():
                return True
            close()
        return _enable(_bootstrap_session if bootstrap is None else bootstrap)
    if _ACTIVE_SESSION is not None:
        close()
    return False


def close() -> bool:
    """Sessionを終了し、成功時だけ再試行用参照を解放する。"""

    _require_main_thread("close")
    global _ACTIVE_SESSION, _ACTIVE_STARTED
    session = _ACTIVE_SESSION
    if session is None:
        return True
    try:
        result = session.close()
    except BaseException as error:
        raise CameraUiError("Camera Sync close failed") from error
    if result is not True and not _session_closed(session):
        raise CameraUiError("Camera Sync close did not complete")
    _ACTIVE_SESSION = None
    _ACTIVE_STARTED = False
    return True


def create_menu_item(parent_menu: Any, *, cmds_module: Any | None = None) -> Any:
    """Animation menuへCamera Sync checkboxを一つ追加する。"""

    maya_cmds = _resolve_cmds(cmds_module)
    menu_item = getattr(maya_cmds, "menuItem", None)
    if not callable(menu_item):
        raise CameraUiError("cmds.menuItem is unavailable")
    global _menu_item, _menu_cmds
    _menu_cmds = None if cmds_module is None else maya_cmds
    _menu_item = menu_item(
        parent=parent_menu,
        label=CAMERA_MENU_LABEL,
        checkBox=is_enabled(),
        command=menu_callback,
        annotation=CAMERA_MENU_ANNOTATION,
    )
    return _menu_item


def menu_callback(*args: Any, bootstrap: Callable[[], Any] | None = None, cmds_module: Any | None = None) -> bool:
    """menu callbackを例外なしで処理し、失敗時はOFFへ戻す。"""

    maya_cmds = _resolve_cmds(cmds_module or _menu_cmds)
    try:
        result = set_enabled(_requested_state(args, maya_cmds), bootstrap=bootstrap)
    except BaseException as error:
        result = is_enabled()
        try:
            maya_cmds.warning(f"Camera Syncを変更できませんでした: {type(error).__name__}")
        except BaseException:
            pass
    try:
        _set_menu_state(result, maya_cmds)
    except BaseException:
        pass
    return result


def _enable(factory: Callable[[], Any]) -> bool:
    """開始成功後だけSession参照を確定する。"""

    if not callable(factory):
        raise CameraUiError("bootstrap must be callable")
    global _ACTIVE_SESSION, _ACTIVE_STARTED
    session: Any | None = None
    try:
        session = factory()
        if session is None or not callable(getattr(session, "start", None)):
            raise CameraUiError("bootstrap returned an invalid Session")
        if session.start() is not True:
            raise CameraUiError("Camera Sync start did not complete")
    except BaseException as error:
        if session is not None and callable(getattr(session, "close", None)):
            try:
                close_result = session.close()
            except BaseException as close_error:
                _ACTIVE_SESSION = session
                _ACTIVE_STARTED = False
                raise CameraUiError("Camera Sync start failed and cleanup failed") from close_error
            if close_result is not True and not _session_closed(session):
                _ACTIVE_SESSION = session
                _ACTIVE_STARTED = False
                raise CameraUiError("Camera Sync start failed and cleanup did not complete") from error
        _ACTIVE_SESSION = None
        _ACTIVE_STARTED = False
        if isinstance(error, CameraUiError):
            raise
        raise CameraUiError("Camera Sync start failed") from error
    _ACTIVE_SESSION = session
    _ACTIVE_STARTED = True
    return True


def _refresh_menu_state() -> bool:
    """終端通知時にcheckboxを実Session状態へ合わせる。"""

    _require_main_thread("refresh")
    actual = is_enabled()
    _set_menu_state(actual, _resolve_cmds(_menu_cmds))
    return actual


def _session_terminal(session: Any) -> bool:
    status = getattr(getattr(session, "lifecycle", None), "status", None)
    return bool(status is not None and (getattr(status, "failed", False) or getattr(status, "closed", False)))


def _session_closed(session: Any) -> bool:
    status = getattr(getattr(session, "lifecycle", None), "status", None)
    return bool(status is not None and getattr(status, "closed", False))


def _requested_state(args: tuple[Any, ...], maya_cmds: Any) -> bool:
    if args and isinstance(args[0], bool):
        return args[0]
    if _menu_item is None:
        raise CameraUiError("Camera Sync menu item is unavailable")
    value = maya_cmds.menuItem(_menu_item, query=True, checkBox=True)
    if not isinstance(value, bool):
        raise CameraUiError("Camera Sync checkbox state is invalid")
    return value


def _resolve_cmds(cmds_module: Any | None) -> Any:
    resolved = _MAYA_CMDS if cmds_module is None else cmds_module
    if resolved is None:
        raise CameraUiError("Maya cmds is unavailable; inject cmds_module")
    return resolved


def _set_menu_state(value: bool, maya_cmds: Any) -> None:
    if _menu_item is not None:
        maya_cmds.menuItem(_menu_item, edit=True, checkBox=value)


def _require_main_thread(operation: str) -> None:
    if threading.main_thread().ident != threading.get_ident():
        raise CameraUiError(f"Camera Sync {operation} must run on the Maya Main Thread")


__all__ = (
    "CAMERA_MENU_ANNOTATION",
    "CAMERA_MENU_LABEL",
    "CameraUiError",
    "active_camera_session",
    "close",
    "create_menu_item",
    "is_enabled",
    "menu_callback",
    "set_enabled",
)
