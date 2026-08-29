"""Mayaのactive viewport cameraをCommon Cameraへ投影する。"""

from __future__ import annotations

import math
import threading
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from ywta_link.camera import Camera
from ywta_link.entity_ref import EntityReference
from ywta_link.time import RationalRate, Time
from ywta_link.transform import CoordinateSystem, Transform

from .playback_host import CallbackErrorStatus

try:
    import maya.api.OpenMaya as _OPEN_MAYA
except ImportError:  # Maya外でのimportと依存注入テストを許可する。
    _OPEN_MAYA = None

try:
    import maya.api.OpenMayaAnim as _OPEN_MAYA_ANIM
except ImportError:  # Maya外でのimportと依存注入テストを許可する。
    _OPEN_MAYA_ANIM = None

try:
    import maya.api.OpenMayaUI as _OPEN_MAYA_UI
except ImportError:  # Maya外でのimportと依存注入テストを許可する。
    _OPEN_MAYA_UI = None

try:
    import maya.cmds as _MAYA_CMDS
except ImportError:  # Maya外でのimportと依存注入テストを許可する。
    _MAYA_CMDS = None


class MayaCameraHostError(RuntimeError):
    """Maya Camera Host bridgeの設定または状態が不正である。"""


class MayaCameraHostUnavailableError(MayaCameraHostError):
    """必要なMaya APIが利用できない。"""


@dataclass(frozen=True)
class MayaCameraBinding:
    """Host生成時に固定したactive viewport camera binding。"""

    camera_path: Any
    transform_path: Any
    camera_fn: Any
    transform_fn: Any
    entity_ref: EntityReference
    aspect_ratio: float


_INCH_TO_MM = 25.4
_CM_TO_MM = 10.0


class MayaCameraHost:
    """active viewport cameraのcallback、snapshot、Main Thread applyを担当する。"""

    def __init__(
        self,
        on_change: Callable[[Camera], None],
        *,
        api: Any = None,
        binding: MayaCameraBinding | None = None,
        aspect_ratio: float | None = None,
        time_provider: Callable[[], Time] | None = None,
    ) -> None:
        """Maya API依存とactive camera bindingを一度だけ解決する。"""

        if not callable(on_change):
            raise MayaCameraHostError("on_change must be callable")
        if time_provider is not None and not callable(time_provider):
            raise MayaCameraHostError("time_provider must be callable")
        self._api = _OPEN_MAYA if api is None else api
        if self._api is None:
            raise MayaCameraHostUnavailableError("Maya Python API is unavailable")
        self._binding = binding or self._capture_binding(aspect_ratio)
        _positive_value(self._binding.aspect_ratio, "aspect_ratio")
        self._time_provider = time_provider or self._default_time
        self._on_change = on_change
        self._owner_thread_id = threading.get_ident()
        self._callback_ids: list[Any] = []
        self._dirty = False
        self._registered = False
        self._applying = False
        self._suppressed_signature: tuple[Any, ...] | None = None
        self._failed = False
        self._last_error: CallbackErrorStatus | None = None
        self._error_count = 0

    @property
    def registered(self) -> bool:
        """callbackが登録済みかを返す。"""

        return self._registered

    @property
    def callback_ids(self) -> tuple[Any, ...]:
        """解除対象callback IDのimmutable snapshotを返す。"""

        return tuple(self._callback_ids)

    @property
    def failed(self) -> bool:
        """terminal failureで隔離済みかを返す。"""

        return self._failed

    @property
    def last_error(self) -> CallbackErrorStatus | None:
        """最後に隔離したcallback例外のstatusを返す。"""

        return self._last_error

    def register(self) -> bool:
        """world matrixとcamera shapeのcallbackを一度だけ登録する。"""

        self._assert_owner_thread("register")
        self._assert_healthy("register")
        if self._registered:
            return False
        dag_message = getattr(self._api, "MDagMessage", None)
        node_message = getattr(self._api, "MNodeMessage", None)
        add_world = getattr(dag_message, "addWorldMatrixModifiedCallback", None)
        add_attribute = getattr(node_message, "addAttributeChangedCallback", None)
        if not callable(add_world) or not callable(add_attribute):
            raise MayaCameraHostUnavailableError("MDagMessage and MNodeMessage callbacks are required")
        try:
            self._callback_ids.append(add_world(self._binding.transform_path, self._camera_callback))
            camera_node = _member_value(self._binding.camera_path, "node")
            self._callback_ids.append(add_attribute(camera_node, self._camera_callback))
        except BaseException as exc:
            try:
                self._remove_callbacks_safely()
            except BaseException:
                self._registered = bool(self._callback_ids)
                raise MayaCameraHostError("Maya camera callback registration failed; cleanup failed") from exc
            self._registered = False
            raise MayaCameraHostError("Maya camera callback registration failed") from exc
        self._registered = True
        return True

    def unregister(self) -> bool:
        """登録済みcallbackを個別解除し、失敗IDだけを再試行用に残す。"""

        self._assert_owner_thread("unregister")
        if not self._callback_ids:
            self._registered = False
            return False
        try:
            self._remove_callbacks_safely()
        except BaseException as exc:
            self._registered = bool(self._callback_ids)
            raise MayaCameraHostError("Maya camera callback removal failed") from exc
        self._registered = False
        self._dirty = False
        return True

    close = unregister

    def quarantine(self) -> bool:
        """callback解除前でもlocal変更通知を即時停止する。"""

        self._assert_owner_thread("quarantine")
        if self._failed:
            return False
        self._failed = True
        self._dirty = False
        return True

    def snapshot(self) -> Camera:
        """固定済みCameraからCommon Camera snapshotを取得する。"""

        self._assert_owner_thread("snapshot")
        self._assert_healthy("snapshot")
        try:
            camera = self._read_snapshot()
        except BaseException as exc:
            self._record_error("snapshot", exc)
            raise
        self._dirty = False
        return camera

    def flush(self) -> bool:
        """保留中のCamera変更を1つのCommon Cameraとして通知する。"""

        self._assert_owner_thread("flush")
        self._assert_healthy("flush")
        if not self._dirty:
            return False
        try:
            camera = self.snapshot()
            signature = _camera_signature(camera)
            if signature == self._suppressed_signature:
                self._suppressed_signature = None
                return False
            self._suppressed_signature = None
            self._on_change(camera)
        except BaseException as exc:
            if not self._failed:
                self._record_error("flush", exc)
            raise MayaCameraHostError("Maya camera flush failed") from exc
        return True

    def apply(self, camera: Camera) -> None:
        """Remote Cameraを固定済みCameraへMain Thread上で適用する。"""

        self._assert_owner_thread("apply")
        self._assert_healthy("apply")
        if not isinstance(camera, Camera):
            raise MayaCameraHostError("camera must be a Camera")
        if not math.isclose(camera.aspect_ratio, self._binding.aspect_ratio, rel_tol=1e-9, abs_tol=0.0):
            raise MayaCameraHostError("camera aspect_ratio must match the bound Maya output aspect")
        self._applying = True
        try:
            self._apply_transform(camera.transform)
            self._apply_shape(camera)
            self._suppressed_signature = _camera_signature(self._read_snapshot())
            self._dirty = False
        except BaseException as exc:
            self._record_error("apply", exc)
            raise MayaCameraHostError("Maya camera apply failed") from exc
        finally:
            self._applying = False

    def _read_snapshot(self) -> Camera:
        """Maya API値をmm、RH Y-up/-ZのCommon Cameraへ変換する。"""

        camera_fn = self._binding.camera_fn
        transform = self._read_transform()
        projection = "orthographic" if bool(_member_value(camera_fn, "isOrtho", False)) else "perspective"
        near = _finite_value(_member_value(camera_fn, "nearClippingPlane"), "near clip") * _CM_TO_MM
        far = _finite_value(_member_value(camera_fn, "farClippingPlane"), "far clip") * _CM_TO_MM
        focus = _optional_positive(_finite_value(_member_value(camera_fn, "focusDistance", None)) * _CM_TO_MM)
        f_stop = _optional_positive(_member_value(camera_fn, "fStop", None))
        common = {
            "entity_ref": self._binding.entity_ref,
            "transform": transform,
            "time": self._time_provider(),
            "projection": projection,
            "focal_length": None,
            "horizontal_aperture": None,
            "vertical_aperture": None,
            "aperture_offset": None,
            "clipping_range": (near, far),
            "focus_distance": focus,
            "f_stop": f_stop,
            "exposure": None,
            "orthographic_size": None,
            "film_fit": None,
            "gate_fit": None,
            "aspect_ratio": self._binding.aspect_ratio,
            "change_id": uuid.uuid4().hex,
        }
        if projection == "perspective":
            common.update(
                focal_length=_positive_value(_member_value(camera_fn, "focalLength"), "focal_length"),
                horizontal_aperture=_positive_value(
                    _member_value(camera_fn, "horizontalFilmAperture") * _INCH_TO_MM,
                    "horizontal_aperture",
                ),
                vertical_aperture=_positive_value(
                    _member_value(camera_fn, "verticalFilmAperture") * _INCH_TO_MM,
                    "vertical_aperture",
                ),
                aperture_offset=(
                    _finite_value(_member_value(camera_fn, "horizontalFilmOffset", 0.0) * _INCH_TO_MM),
                    _finite_value(_member_value(camera_fn, "verticalFilmOffset", 0.0) * _INCH_TO_MM),
                ),
                film_fit=self._film_fit_name(_member_value(camera_fn, "filmFit", None)),
            )
        else:
            # Maya orthoWidthは水平全幅、Commonは垂直全高。
            common["orthographic_size"] = _positive_value(
                _finite_value(_member_value(camera_fn, "orthoWidth")) * _CM_TO_MM / self._binding.aspect_ratio,
                "orthographic_size",
            )
        return Camera(**common)

    def _read_transform(self) -> Transform:
        """inclusive matrixからworld transformをmmで取得する。"""

        matrix = _member_value(self._binding.transform_path, "inclusiveMatrix")
        matrix_type = getattr(self._api, "MTransformationMatrix", None)
        space = getattr(getattr(self._api, "MSpace", None), "kTransform", 0)
        if matrix_type is None:
            raise MayaCameraHostUnavailableError("MTransformationMatrix is unavailable")
        transform = matrix_type(matrix)
        translation = transform.translation(space)
        rotation = transform.rotation(asQuaternion=True)
        scale = transform.scale(space)
        return Transform(
            entity_ref=self._binding.entity_ref,
            translation=tuple(_finite_value(value) * _CM_TO_MM for value in (translation.x, translation.y, translation.z)),
            rotation=tuple(_finite_value(value) for value in (rotation.x, rotation.y, rotation.z, rotation.w)),
            scale=tuple(_finite_value(value) for value in scale),
            coordinate_system=CoordinateSystem("world", "right", "+y", "-z", None),
            unit="millimeter",
        )

    def _apply_transform(self, transform: Transform) -> None:
        """Common world transformをMaya local matrixへ変換して適用する。"""

        matrix_type = getattr(self._api, "MTransformationMatrix", None)
        vector_type = getattr(self._api, "MVector", None)
        quaternion_type = getattr(self._api, "MQuaternion", None)
        space = getattr(getattr(self._api, "MSpace", None), "kTransform", 0)
        if matrix_type is None or vector_type is None or quaternion_type is None:
            raise MayaCameraHostUnavailableError("MTransformationMatrix, MVector and MQuaternion are required")
        world = matrix_type()
        world.setTranslation(vector_type(*(value / _CM_TO_MM for value in transform.translation)), space)
        world.setRotation(quaternion_type(*transform.rotation))
        world.setScale(transform.scale, space)
        parent_inverse = _member_value(self._binding.transform_path, "exclusiveMatrixInverse")
        local = matrix_type(world.asMatrix() * parent_inverse)
        setter = getattr(self._binding.transform_fn, "setTransformation", None)
        if not callable(setter):
            raise MayaCameraHostUnavailableError("MFnTransform.setTransformation is unavailable")
        setter(local)

    def _apply_shape(self, camera: Camera) -> None:
        """Common lens値をMFnCameraへ適用する。"""

        camera_fn = self._binding.camera_fn
        _set_member(camera_fn, "isOrtho", camera.projection == "orthographic")
        _set_member(camera_fn, "nearClippingPlane", camera.clipping_range[0] / _CM_TO_MM)
        _set_member(camera_fn, "farClippingPlane", camera.clipping_range[1] / _CM_TO_MM)
        if camera.focus_distance is not None:
            _set_member(camera_fn, "focusDistance", camera.focus_distance / _CM_TO_MM)
        if camera.f_stop is not None:
            _set_member(camera_fn, "fStop", camera.f_stop)
        if camera.projection == "orthographic":
            _set_member(camera_fn, "orthoWidth", camera.orthographic_size / _CM_TO_MM * self._binding.aspect_ratio)
            return
        _set_member(camera_fn, "focalLength", camera.focal_length)
        _set_member(camera_fn, "horizontalFilmAperture", camera.horizontal_aperture / _INCH_TO_MM)
        _set_member(camera_fn, "verticalFilmAperture", camera.vertical_aperture / _INCH_TO_MM)
        _set_member(camera_fn, "horizontalFilmOffset", camera.aperture_offset[0] / _INCH_TO_MM)
        _set_member(camera_fn, "verticalFilmOffset", camera.aperture_offset[1] / _INCH_TO_MM)

    def _camera_callback(self, *_args: Any) -> None:
        """world matrixまたはshape変更をdirty flagへ変換する。"""

        self._mark_dirty()

    def _mark_dirty(self) -> None:
        """callback内では単一dirty flagだけを立てる。"""

        if self._failed or self._applying:
            return
        self._dirty = True

    def _capture_binding(self, aspect_ratio: float | None) -> MayaCameraBinding:
        """生成時のactive viewport cameraとoutput aspectを固定する。"""

        view_type = getattr(_OPEN_MAYA_UI, "M3dView", None)
        active_view = getattr(view_type, "active3dView", None)
        if not callable(active_view):
            raise MayaCameraHostUnavailableError("M3dView.active3dView is unavailable")
        view = active_view()
        path_type = getattr(self._api, "MDagPath", None)
        camera_type = getattr(self._api, "MFnCamera", None)
        transform_type = getattr(self._api, "MFnTransform", None)
        if path_type is None or camera_type is None or transform_type is None:
            raise MayaCameraHostUnavailableError("MDagPath, MFnCamera and MFnTransform are required")
        camera_path = path_type(view.getCamera())
        transform_path = path_type(camera_path)
        transform_path.pop()
        camera_fn = camera_type(camera_path)
        transform_fn = transform_type(transform_path)
        dependency_fn = getattr(self._api, "MFnDependencyNode", None)
        if dependency_fn is None:
            raise MayaCameraHostUnavailableError("MFnDependencyNode is unavailable")
        node_fn = dependency_fn(_member_value(camera_path, "node"))
        node_uuid = str(_member_value(_member_value(node_fn, "uuid"), "asString"))
        display_name = str(_member_value(camera_path, "partialPathName"))
        namespace = display_name.rsplit(":", 1)[0] if ":" in display_name else None
        ratio = _default_output_aspect() if aspect_ratio is None else aspect_ratio
        _positive_value(ratio, "aspect_ratio")
        return MayaCameraBinding(
            camera_path=camera_path,
            transform_path=transform_path,
            camera_fn=camera_fn,
            transform_fn=transform_fn,
            entity_ref=EntityReference("maya:camera:" + node_uuid, "camera", display_name, namespace),
            aspect_ratio=float(ratio),
        )

    def _default_time(self) -> Time:
        """MAnimControlの現在時刻をnanosecond tickへ投影する。"""

        anim_control = getattr(_OPEN_MAYA_ANIM, "MAnimControl", None)
        mtime = getattr(self._api, "MTime", None)
        seconds_unit = getattr(mtime, "kSeconds", None)
        if anim_control is None or seconds_unit is None:
            raise MayaCameraHostUnavailableError("MAnimControl.currentTime and MTime.kSeconds are required")
        current = _member_value(anim_control, "currentTime")
        as_units = getattr(current, "asUnits", None)
        if not callable(as_units):
            raise MayaCameraHostUnavailableError("MTime.asUnits is unavailable")
        seconds = _finite_value(as_units(seconds_unit))
        ticks = round(seconds * 1_000_000_000)
        return Time(ticks, None, None, RationalRate(1_000_000_000, 1))

    def _film_fit_name(self, value: Any) -> str | None:
        """MFnCamera filmFit enumをCommon文字列へ変換する。"""

        camera_fn = self._binding.camera_fn
        for common, maya_name in (
            ("horizontal", "kHorizontalFilmFit"),
            ("vertical", "kVerticalFilmFit"),
            ("fill", "kFillFilmFit"),
            ("overscan", "kOverscanFilmFit"),
        ):
            if value == getattr(camera_fn, maya_name, object()):
                return common
        return None

    def _remove_callbacks_safely(self) -> None:
        """成功したcallback IDだけを台帳から除外する。"""

        remove = getattr(getattr(self._api, "MMessage", None), "removeCallback", None)
        if not callable(remove):
            raise MayaCameraHostUnavailableError("MMessage.removeCallback is unavailable")
        failures: list[BaseException] = []
        for callback_id in tuple(self._callback_ids):
            try:
                remove(callback_id)
            except BaseException as exc:
                failures.append(exc)
            else:
                self._callback_ids.remove(callback_id)
        if failures:
            raise failures[0]

    def _assert_owner_thread(self, operation: str) -> None:
        """Maya Main Thread以外からの操作を拒否する。"""

        if threading.get_ident() != self._owner_thread_id:
            raise MayaCameraHostError(f"{operation} must run on the Maya Main Thread")

    def _assert_healthy(self, operation: str) -> None:
        """terminal failure後の同期操作を拒否する。"""

        if self._failed:
            raise MayaCameraHostError(f"{operation} is unavailable after Camera Host failure")

    def _record_error(self, callback: str, error: BaseException) -> None:
        """例外本体を保持せず、Hostをterminal failureとして隔離する。"""

        self._failed = True
        self._dirty = False
        self._error_count += 1
        try:
            message = str(error)
        except BaseException:
            message = "<unprintable exception>"
        self._last_error = CallbackErrorStatus(callback, type(error).__name__, message[:1024], self._error_count)


def _default_output_aspect() -> float:
    """Maya output resolutionからdevice aspect ratioを取得する。"""

    if _MAYA_CMDS is None:
        raise MayaCameraHostUnavailableError("maya.cmds is required to query output aspect ratio")
    value = _MAYA_CMDS.getAttr("defaultResolution.deviceAspectRatio")
    return _positive_value(value, "aspect_ratio")


def _camera_signature(camera: Camera) -> tuple[Any, ...]:
    """change IDとTimeを除くMaya Camera状態を比較する。"""

    return tuple(
        getattr(camera, name)
        for name in (
            "transform",
            "projection",
            "focal_length",
            "horizontal_aperture",
            "vertical_aperture",
            "aperture_offset",
            "clipping_range",
            "focus_distance",
            "f_stop",
            "exposure",
            "orthographic_size",
            "film_fit",
            "gate_fit",
            "aspect_ratio",
        )
    )


def _member_value(instance: Any, name: str, default: Any = None) -> Any:
    """method/propertyどちらのMaya APIでも値を取得する。"""

    value = getattr(instance, name, default)
    return value() if callable(value) else value


def _set_member(instance: Any, name: str, value: Any) -> None:
    """Maya API propertyへ値を設定する。"""

    setter = getattr(instance, "set" + name[0].upper() + name[1:], None)
    if callable(setter):
        setter(value)
        return
    if not hasattr(instance, name):
        raise MayaCameraHostUnavailableError(f"MFnCamera.{name} is unavailable")
    setattr(instance, name, value)


def _finite_value(value: Any, field_name: str = "value") -> float:
    """boolでない有限数をfloatへ変換する。"""

    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise MayaCameraHostError(f"{field_name} must be a finite number")
    return float(value)


def _positive_value(value: Any, field_name: str) -> float:
    """正の有限数をfloatへ変換する。"""

    result = _finite_value(value, field_name)
    if result <= 0:
        raise MayaCameraHostError(f"{field_name} must be positive")
    return result


def _optional_positive(value: Any) -> float | None:
    """正の有限数以外を未提供へ変換する。"""

    try:
        result = _finite_value(value)
    except MayaCameraHostError:
        return None
    return result if result > 0 else None


__all__ = (
    "CallbackErrorStatus",
    "MayaCameraBinding",
    "MayaCameraHost",
    "MayaCameraHostError",
    "MayaCameraHostUnavailableError",
)
