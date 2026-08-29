"""Maya Animation menu向けPlayback Syncの最小UI境界。"""

from __future__ import annotations

import threading
from typing import Any, Callable

from .session import bootstrap_maya_playback_session

try:
    import maya.cmds as _MAYA_CMDS
except ImportError:  # Maya外の標準Pythonでは依存注入を使う。
    _MAYA_CMDS = None

cmds = _MAYA_CMDS


PLAYBACK_MENU_LABEL = "Playback Sync"
PLAYBACK_DIVIDER_LABEL = "YWTA Link"
PLAYBACK_MENU_ICON = "play_regular.png"
PLAYBACK_MENU_ANNOTATION = "他DCCとPlaybackを同期します。frame rateを変更した場合は一度OFF/ONしてください"


class PlaybackUiError(RuntimeError):
    """Playback Sync menuの状態遷移またはcleanupに失敗したことを表す。"""


_ACTIVE_SESSION: Any | None = None
_menu_item: Any | None = None
_menu_cmds: Any | None = None


def is_enabled() -> bool:
    """現在Playback Syncが有効かを返す。"""

    return _ACTIVE_SESSION is not None and not _session_terminal(_ACTIVE_SESSION)


def active_playback_session() -> Any | None:
    """現在moduleが所有するPlayback Sessionを返す。"""

    return _ACTIVE_SESSION


def _bootstrap_session() -> Any:
    """Maya向けdefault bootstrapをUIから遅延実行する。"""

    return bootstrap_maya_playback_session(lifecycle_options={"on_terminal": _refresh_menu_state})


def _refresh_menu_state() -> bool:
    """checkboxをMain Thread上で実際のSession状態へ合わせる。"""

    _require_main_thread("refresh")
    actual = is_enabled()
    maya_cmds = cmds if _menu_cmds is None else _menu_cmds
    _set_menu_state(actual, maya_cmds)
    return actual


def set_enabled(
    enabled: bool,
    *,
    bootstrap: Callable[[], Any] | None = None,
    cmds_module: Any | None = None,
) -> bool:
    """Playback Sync Sessionを開始または終了する。

    ``bootstrap``と``cmds_module``はMaya外のテストから依存を注入するための境界。
    Sessionは開始が成功した後だけmodule-owned参照へ移される。終了に失敗した場合は
    同じ参照を保持し、次のOFFまたはreloadで再試行できる。
    """

    if not isinstance(enabled, bool):
        raise PlaybackUiError("enabled must be a bool")

    _require_main_thread("set_enabled")
    if enabled:
        if _ACTIVE_SESSION is not None:
            if not _session_terminal(_ACTIVE_SESSION):
                return True
            close(cmds_module=cmds_module)
        return _enable(bootstrap)

    if _ACTIVE_SESSION is None:
        return False
    close(cmds_module=cmds_module)
    return False


def close(*, cmds_module: Any | None = None) -> bool:
    """所有中のSessionを終了し、成功した場合だけ所有参照を解放する。"""

    del cmds_module  # 将来のmenu状態復元用に境界を残し、現在はUIを変更しない。
    _require_main_thread("close")
    global _ACTIVE_SESSION
    session = _ACTIVE_SESSION
    if session is None:
        return True
    try:
        result = session.close()
    except BaseException as error:
        raise PlaybackUiError("Playback Sync close failed") from error
    if result is not True and not _session_closed(session):
        raise PlaybackUiError("Playback Sync close did not complete")
    _ACTIVE_SESSION = None
    return True


def create_menu_item(parent_menu: Any, *, cmds_module: Any | None = None) -> Any:
    """Animation menuへdividerとPlayback Sync checkboxを一つだけ追加する。"""

    maya_cmds = _resolve_cmds(cmds_module)
    divider = getattr(maya_cmds, "menuItem", None)
    if not callable(divider):
        raise PlaybackUiError("cmds.menuItem is unavailable")
    divider(parent=parent_menu, divider=True, dividerLabel=PLAYBACK_DIVIDER_LABEL)
    global _menu_item
    global _menu_cmds
    _menu_cmds = None if cmds_module is None else maya_cmds
    _menu_item = divider(
        parent=parent_menu,
        label=PLAYBACK_MENU_LABEL,
        checkBox=is_enabled(),
        command=menu_callback,
        image=PLAYBACK_MENU_ICON,
        annotation=PLAYBACK_MENU_ANNOTATION,
    )
    return _menu_item


def menu_callback(
    *args: Any,
    bootstrap: Callable[[], Any] | None = None,
    cmds_module: Any | None = None,
) -> bool:
    """Maya menu callbackを例外なしで処理し、失敗時はcheckboxを復元する。"""

    maya_cmds = cmds if _menu_cmds is None else _menu_cmds
    if cmds_module is not None:
        maya_cmds = cmds_module
    try:
        requested = _requested_state(args, maya_cmds)
        result = set_enabled(requested, bootstrap=bootstrap)
        _set_menu_state(result, maya_cmds)
        return result
    except BaseException as error:
        actual = is_enabled()
        try:
            _set_menu_state(actual, maya_cmds)
        except BaseException:
            pass
        try:
            maya_cmds.warning(f"Playback Syncを変更できませんでした: {type(error).__name__}")
        except BaseException:
            pass
        return actual


def _enable(bootstrap: Callable[[], Any] | None) -> bool:
    """Sessionを開始し、開始成功後だけactive参照を確定する。"""

    global _ACTIVE_SESSION
    factory = _bootstrap_session if bootstrap is None else bootstrap
    if not callable(factory):
        raise PlaybackUiError("bootstrap must be callable")
    session: Any | None = None
    try:
        session = factory()
        if session is None or not callable(getattr(session, "start", None)):
            raise PlaybackUiError("bootstrap returned an invalid Session")
        if session.start() is not True:
            raise PlaybackUiError("Playback Sync start did not complete")
    except BaseException as error:
        if session is not None and callable(getattr(session, "close", None)):
            try:
                session.close()
            except BaseException as close_error:
                _ACTIVE_SESSION = session
                raise PlaybackUiError("Playback Sync start failed and cleanup failed") from close_error
        _ACTIVE_SESSION = None
        if isinstance(error, PlaybackUiError):
            raise
        raise PlaybackUiError("Playback Sync start failed") from error
    _ACTIVE_SESSION = session
    return True


def _session_terminal(session: Any) -> bool:
    """Lifecycle status上でfailedまたはclosedのSessionを判定する。"""

    status = getattr(getattr(session, "lifecycle", None), "status", None)
    return bool(status is not None and (getattr(status, "failed", False) or getattr(status, "closed", False)))


def _session_closed(session: Any) -> bool:
    """close結果がFalseでも既にclosedなら解放済みとして扱う。"""

    status = getattr(getattr(session, "lifecycle", None), "status", None)
    return bool(status is not None and getattr(status, "closed", False))


def _require_main_thread(operation: str) -> None:
    """Maya UIとSession lifecycleをPython Main Threadへ限定する。"""

    if threading.main_thread().ident != threading.get_ident():
        raise PlaybackUiError(f"Playback Sync {operation} must run on the Maya Main Thread")


def _requested_state(args: tuple[Any, ...], maya_cmds: Any) -> bool:
    """Mayaが更新したcheckbox値を読む。"""

    if args and isinstance(args[0], bool):
        return args[0]
    if _menu_item is None:
        raise PlaybackUiError("Playback Sync menu item is unavailable")
    query = getattr(maya_cmds, "menuItem", None)
    if not callable(query):
        raise PlaybackUiError("cmds.menuItem is unavailable")
    value = query(_menu_item, query=True, checkBox=True)
    if not isinstance(value, bool):
        raise PlaybackUiError("Playback Sync checkbox state is invalid")
    return value


def _resolve_cmds(cmds_module: Any | None) -> Any:
    """注入されたMaya cmds、または実Mayaのcmdsを解決する。"""

    resolved = cmds if cmds_module is None else cmds_module
    if resolved is None:
        raise PlaybackUiError("Maya cmds is unavailable; inject cmds_module")
    return resolved


def _set_menu_state(value: bool, maya_cmds: Any) -> None:
    """checkboxを実際のSession状態へ合わせる。"""

    if _menu_item is None:
        return
    edit = getattr(maya_cmds, "menuItem", None)
    if not callable(edit):
        raise PlaybackUiError("cmds.menuItem is unavailable")
    edit(_menu_item, edit=True, checkBox=value)


__all__ = (
    "PLAYBACK_DIVIDER_LABEL",
    "PLAYBACK_MENU_ANNOTATION",
    "PLAYBACK_MENU_ICON",
    "PLAYBACK_MENU_LABEL",
    "PlaybackUiError",
    "active_playback_session",
    "close",
    "create_menu_item",
    "is_enabled",
    "menu_callback",
    "set_enabled",
)
