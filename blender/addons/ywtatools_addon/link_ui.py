"""YWTA Linkの最小Playback / Camera Sync UI。"""

from __future__ import annotations

from typing import Any

try:
    import bpy as _BPY
    from bpy.props import BoolProperty as _BoolProperty
    from bpy.types import Panel as _Panel
except ImportError:  # Blender外の標準Pythonテストではfake bpyを注入する。
    _BPY = None
    _BoolProperty = None

    class _Panel:
        """Blender外でPanel定義を読み込むための最小stub。"""


class LinkUIError(RuntimeError):
    """YWTA Link UIの登録またはPlayback Session終了に失敗した。"""


PLAYBACK_SYNC_PROPERTY = "ywta_playback_sync"
CAMERA_SYNC_PROPERTY = "ywta_camera_sync"

# importlib.reload()時も旧Sessionと登録台帳を保持する。
if "_ACTIVE_SESSION" not in globals():
    _ACTIVE_SESSION: object | None = None
if "_ACTIVE_CAMERA_SESSION" not in globals():
    _ACTIVE_CAMERA_SESSION: object | None = None
if "_PROPERTY_REGISTERED" not in globals():
    _PROPERTY_REGISTERED = False
if "_OWNED_PROPERTIES" not in globals():
    _OWNED_PROPERTIES: set[str] = set()
if "_PANEL_REGISTERED" not in globals():
    _PANEL_REGISTERED = False


def _bootstrap_session() -> object:
    """Blender向けdefault bootstrapを遅延importして実行する。"""

    return bootstrap_blender_playback_session()


def bootstrap_blender_playback_session() -> object:
    """Blender向けdefault bootstrapを公開する遅延import境界。"""

    from .link_session import bootstrap_blender_playback_session as bootstrap

    return bootstrap()


def _bootstrap_camera_session() -> object:
    """Blender向けCamera bootstrapを遅延importして実行する。"""

    return bootstrap_blender_camera_session()


def bootstrap_blender_camera_session() -> object:
    """Blender向けdefault Camera bootstrapの遅延import境界。"""

    from .link_camera_session import bootstrap_blender_camera_session as bootstrap

    return bootstrap()


if "YWTA_PT_Link" not in globals():

    class YWTA_PT_Link(_Panel):
        """View3D sidebarへLink Sync checkboxだけを表示する。"""

        bl_idname = "YWTA_PT_link"
        bl_label = "Link"
        bl_space_type = "VIEW_3D"
        bl_region_type = "UI"
        bl_category = "YWTA"

        def draw(self, context: Any) -> None:
            """PlaybackとCamera Syncを各一つのcheckboxで切り替える。"""

            self.layout.prop(context.window_manager, PLAYBACK_SYNC_PROPERTY)
            self.layout.prop(context.window_manager, CAMERA_SYNC_PROPERTY)


def _resolve_bpy() -> Any:
    """注入済みまたは実Blenderのbpy moduleを取得する。"""

    if _BPY is not None:
        return _BPY
    try:
        import bpy  # type: ignore[import-not-found]
    except ImportError as error:
        raise LinkUIError("Blender Python API is unavailable; inject bpy for tests") from error
    return bpy


def _session_is_active(session: object) -> bool:
    """Sessionの実状態からActiveかを判定する。"""

    lifecycle = getattr(session, "lifecycle", None)
    status = getattr(lifecycle, "status", None)
    if status is not None and hasattr(status, "started"):
        if getattr(status, "started") is not True:
            return False
        if getattr(status, "closed", False) is not False:
            return False
        if getattr(status, "failed", False) is not False:
            return False
        if hasattr(status, "timer_registered") and getattr(status, "timer_registered") is not True:
            return False
        return True

    if hasattr(session, "_started"):
        return (
            getattr(session, "_started") is True
            and getattr(session, "_closed", False) is False
            and getattr(session, "_failed", False) is False
        )
    if hasattr(session, "started"):
        return (
            getattr(session, "started") is True
            and getattr(session, "closed", False) is False
            and getattr(session, "failed", False) is False
        )
    # 最小fake Sessionはstart()の戻り値を所有状態として扱う。
    return True


def _session_is_closed(session: object) -> bool:
    """Sessionが既に終了済みかを確認する。"""

    # 外側Sessionの所有状態が、Client close retryを含む全体の正本である。
    if hasattr(session, "_closed"):
        return getattr(session, "_closed") is True
    if hasattr(session, "closed"):
        return getattr(session, "closed") is True

    lifecycle = getattr(session, "lifecycle", None)
    status = getattr(lifecycle, "status", None)
    if status is not None and hasattr(status, "closed"):
        return getattr(status, "closed") is True
    return False


def _get_playback_sync(_window_manager: object) -> bool:
    """module-owned Active Sessionの実状態をcheckboxへ返す。"""

    return _ACTIVE_SESSION is not None and _session_is_active(_ACTIVE_SESSION)


def _get_camera_sync(_window_manager: object) -> bool:
    """module-owned Camera Sessionの実状態をcheckboxへ返す。"""

    return _ACTIVE_CAMERA_SESSION is not None and _session_is_active(_ACTIVE_CAMERA_SESSION)


def _report_setter_failure(operation: str, error: BaseException) -> None:
    """Blender property setterから例外を外へ漏らさず記録する。"""

    try:
        print(f"YWTA Link Playback Sync {operation} failed: {type(error).__name__}: {error}")
    except BaseException:
        pass


def _set_playback_sync(_window_manager: object, enabled: bool) -> None:
    """checkbox操作をSession start/closeへ委譲する。"""

    try:
        set_enabled(bool(enabled))
    except BaseException as error:
        _report_setter_failure("enable" if enabled else "disable", error)


def _set_camera_sync(_window_manager: object, enabled: bool) -> None:
    """Camera checkbox操作をSession start/closeへ委譲する。"""

    try:
        set_camera_enabled(bool(enabled))
    except BaseException as error:
        _report_setter_failure("Camera enable" if enabled else "Camera disable", error)


def is_enabled() -> bool:
    """現在Playback Syncが有効かをSession実状態から返す。"""

    return _get_playback_sync(None)


def is_camera_enabled() -> bool:
    """現在Camera Syncが有効かをSession実状態から返す。"""

    return _get_camera_sync(None)


def set_enabled(enabled: bool, *, bootstrap: Any = None) -> bool:
    """Playback Sync Sessionを開始または終了する。"""

    return _set_enabled("Playback", enabled, bootstrap)


def set_camera_enabled(enabled: bool, *, bootstrap: Any = None) -> bool:
    """Camera Sync Sessionを開始または終了する。"""

    return _set_enabled("Camera", enabled, bootstrap)


def _set_enabled(kind: str, enabled: bool, bootstrap: Any) -> bool:
    """指定Sync Sessionを開始または終了する。"""

    if not isinstance(enabled, bool):
        raise LinkUIError("enabled must be a bool")
    session = _active_session(kind)
    if enabled:
        if session is not None:
            if _session_is_active(session):
                return True
            if _session_is_closed(session):
                _store_session(kind, None)
            else:
                # 開始失敗後などの非Active Sessionを先に確実に閉じる。
                _close_session(kind)
        return _enable(kind, bootstrap)
    if session is None:
        return False
    if _session_is_closed(session):
        _store_session(kind, None)
        return False
    _close_session(kind)
    return False


def _enable(kind: str, bootstrap: Any) -> bool:
    """Sessionを開始し、成功後だけmodule-owned参照へ移す。"""

    factory = (_bootstrap_session if kind == "Playback" else _bootstrap_camera_session) if bootstrap is None else bootstrap
    if not callable(factory):
        raise LinkUIError("bootstrap must be callable")
    session: object | None = None
    try:
        session = factory()
        start = getattr(session, "start", None)
        if not callable(start) or start() is not True:
            raise LinkUIError(f"{kind} Sync start did not complete")
    except BaseException as error:
        cleanup_succeeded = False
        if session is not None:
            try:
                close = getattr(session, "close", None)
                if callable(close):
                    cleanup_succeeded = close() is True
            except BaseException as close_error:
                _report_setter_failure("cleanup", close_error)
        if session is not None and not cleanup_succeeded:
            _store_session(kind, session)
        else:
            _store_session(kind, None)
        raise LinkUIError(f"{kind} Sync start failed") from error
    _store_session(kind, session)
    return True


def close() -> bool:
    """所有中のPlayback Sessionを終了する。"""

    return _close_session("Playback")


def close_camera() -> bool:
    """所有中のCamera Sessionを終了する。"""

    return _close_session("Camera")


def _close_session(kind: str) -> bool:
    """所有中のSessionを終了し、成功した場合だけ参照を解放する。"""

    session = _active_session(kind)
    if session is None:
        return True
    close_method = getattr(session, "close", None)
    if not callable(close_method):
        raise LinkUIError(f"{kind} Sync Session does not provide close()")
    try:
        result = close_method()
    except BaseException as error:
        raise LinkUIError(f"{kind} Sync close failed") from error
    if result is not True:
        raise LinkUIError(f"{kind} Sync close did not complete")
    _store_session(kind, None)
    return True


def _active_session(kind: str) -> object | None:
    """指定種別のmodule-owned Sessionを返す。"""

    return _ACTIVE_SESSION if kind == "Playback" else _ACTIVE_CAMERA_SESSION


def _store_session(kind: str, session: object | None) -> None:
    """指定種別のmodule-owned Session参照を更新する。"""

    global _ACTIVE_CAMERA_SESSION, _ACTIVE_SESSION

    if kind == "Playback":
        _ACTIVE_SESSION = session
    else:
        _ACTIVE_CAMERA_SESSION = session


def active_playback_session() -> object | None:
    """現在moduleが所有するPlayback Sessionを返す。"""

    return _ACTIVE_SESSION


def active_camera_session() -> object | None:
    """現在moduleが所有するCamera Sessionを返す。"""

    return _ACTIVE_CAMERA_SESSION


def register() -> None:
    """WindowManager propertyを定義してLink panelを登録する。"""

    global _PANEL_REGISTERED, _PROPERTY_REGISTERED

    bpy = _resolve_bpy()
    bool_property = _BoolProperty
    if bool_property is None:
        try:
            from bpy.props import BoolProperty as bool_property
        except ImportError as error:
            raise LinkUIError("bpy.props.BoolProperty is unavailable") from error

    window_manager_type = getattr(getattr(bpy, "types", None), "WindowManager", None)
    if window_manager_type is None:
        raise LinkUIError("bpy.types.WindowManager is unavailable")
    properties = (
        (
            PLAYBACK_SYNC_PROPERTY,
            "Playback Sync",
            "Playback状態をYWTA Linkの他のDCCと同期する",
            _get_playback_sync,
            _set_playback_sync,
        ),
        (CAMERA_SYNC_PROPERTY, "Camera Sync", "Camera状態をYWTA Linkの他のDCCと同期する", _get_camera_sync, _set_camera_sync),
    )
    created: list[str] = []
    try:
        for name, label, description, getter, setter in properties:
            if hasattr(window_manager_type, name):
                if name not in _OWNED_PROPERTIES:
                    raise LinkUIError(f"WindowManager.{name} already exists and is not owned by YWTA Link")
                continue
            setattr(
                window_manager_type,
                name,
                bool_property(
                    name=label,
                    description=description,
                    default=False,
                    options={"SKIP_SAVE"},
                    get=getter,
                    set=setter,
                ),
            )
            _OWNED_PROPERTIES.add(name)
            created.append(name)
    except BaseException as error:
        _rollback_properties(window_manager_type, created)
        _PROPERTY_REGISTERED = bool(_OWNED_PROPERTIES)
        raise LinkUIError(f"Link Sync property registration failed: {error}") from error
    _PROPERTY_REGISTERED = bool(_OWNED_PROPERTIES)

    if _PANEL_REGISTERED:
        return
    utils = getattr(bpy, "utils", None)
    register_class = getattr(utils, "register_class", None)
    if not callable(register_class):
        raise LinkUIError("bpy.utils.register_class is unavailable")
    try:
        register_class(YWTA_PT_Link)
    except BaseException as error:
        _rollback_properties(window_manager_type, created)
        _PROPERTY_REGISTERED = bool(_OWNED_PROPERTIES)
        raise LinkUIError("Link panel registration failed") from error
    _PANEL_REGISTERED = True


def unregister() -> None:
    """Sessionを終了し、成功後にPanelとWindowManager propertyを削除する。"""

    global _PANEL_REGISTERED, _PROPERTY_REGISTERED

    bpy = _resolve_bpy()
    window_manager_type = getattr(getattr(bpy, "types", None), "WindowManager", None)
    if window_manager_type is None:
        raise LinkUIError("bpy.types.WindowManager is unavailable")

    for kind in ("Camera", "Playback"):
        session = _active_session(kind)
        if session is None:
            continue
        if _session_is_closed(session):
            _store_session(kind, None)
            continue
        try:
            _close_session(kind)
        except BaseException as error:
            # propertyは残し、moduleをunload可能な状態へ進めない。
            raise LinkUIError(f"active {kind} Session close failed") from error

    if _PANEL_REGISTERED:
        unregister_class = getattr(getattr(bpy, "utils", None), "unregister_class", None)
        if not callable(unregister_class):
            raise LinkUIError("bpy.utils.unregister_class is unavailable")
        try:
            unregister_class(YWTA_PT_Link)
        except BaseException as error:
            raise LinkUIError("Link panel unregistration failed") from error
        _PANEL_REGISTERED = False

    for name in (CAMERA_SYNC_PROPERTY, PLAYBACK_SYNC_PROPERTY):
        if name not in _OWNED_PROPERTIES:
            continue
        if not hasattr(window_manager_type, name):
            _OWNED_PROPERTIES.remove(name)
            continue
        try:
            delattr(window_manager_type, name)
        except BaseException as error:
            _PROPERTY_REGISTERED = bool(_OWNED_PROPERTIES)
            raise LinkUIError("Link Sync property removal failed") from error
        _OWNED_PROPERTIES.remove(name)
    _PROPERTY_REGISTERED = bool(_OWNED_PROPERTIES)


def _rollback_properties(window_manager_type: type, created: list[str]) -> None:
    """今回作成したpropertyだけを逆順で戻し、失敗ownershipは保持する。"""

    for name in reversed(created):
        if not hasattr(window_manager_type, name):
            _OWNED_PROPERTIES.discard(name)
            continue
        try:
            delattr(window_manager_type, name)
        except BaseException:
            continue
        _OWNED_PROPERTIES.discard(name)


__all__ = (
    "LinkUIError",
    "CAMERA_SYNC_PROPERTY",
    "PLAYBACK_SYNC_PROPERTY",
    "YWTA_PT_Link",
    "active_camera_session",
    "active_playback_session",
    "bootstrap_blender_camera_session",
    "bootstrap_blender_playback_session",
    "close",
    "close_camera",
    "is_camera_enabled",
    "is_enabled",
    "register",
    "set_camera_enabled",
    "set_enabled",
    "unregister",
)
