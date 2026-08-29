"""Blenderの固定CameraをCommon Camera v1へ投影する。"""

from __future__ import annotations

import math
import threading
import uuid
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Callable

from ywta_link.camera import Camera
from ywta_link.entity_ref import EntityReference
from ywta_link.time import RationalRate, Time
from ywta_link.transform import CoordinateSystem, Transform

from .link_playback import CallbackErrorStatus

try:
    import bpy as _BPY
except ImportError:  # Blender外では依存注入テストを許可する。
    _BPY = None

try:
    from mathutils import Matrix as _MATRIX
    from mathutils import Quaternion as _QUATERNION
    from mathutils import Vector as _VECTOR
except ImportError:  # Blender外ではmatrix_composeを注入する。
    _MATRIX = _QUATERNION = _VECTOR = None


class BlenderCameraHostError(RuntimeError):
    """Blender Camera Host bridgeの設定または状態が不正である。"""


class BlenderCameraHostUnavailableError(BlenderCameraHostError):
    """必要なBlender APIが利用できない。"""


@dataclass(frozen=True)
class BlenderCameraBinding:
    """Host生成時に固定したScene Camera binding。"""

    scene: Any
    camera_object: Any
    camera_data: Any
    entity_ref: EntityReference


# Blender RH Z-upからCommon RH Y-upへのbasis rotation（xyzw）。
_BLENDER_TO_COMMON = (-math.sqrt(0.5), 0.0, 0.0, math.sqrt(0.5))
_COMMON_TO_BLENDER = (math.sqrt(0.5), 0.0, 0.0, math.sqrt(0.5))
_DEPSGRAPH_HANDLER = "depsgraph_update_post"


class BlenderCameraHost:
    """固定Scene Cameraの変更検出、snapshot、Main Thread applyを担当する。"""

    def __init__(
        self,
        on_change: Callable[[Camera], bool],
        *,
        bpy_module: Any = None,
        binding: BlenderCameraBinding | None = None,
        time_provider: Callable[[], Time] | None = None,
        matrix_compose: Callable[[tuple[float, ...], tuple[float, ...], tuple[float, ...]], Any] | None = None,
    ) -> None:
        """Blender依存とscene.cameraを一度だけ解決する。"""

        if not callable(on_change):
            raise BlenderCameraHostError("on_change must be callable")
        if time_provider is not None and not callable(time_provider):
            raise BlenderCameraHostError("time_provider must be callable")
        if matrix_compose is not None and not callable(matrix_compose):
            raise BlenderCameraHostError("matrix_compose must be callable")
        self._bpy = _BPY if bpy_module is None else bpy_module
        if self._bpy is None:
            raise BlenderCameraHostUnavailableError("Blender Python API is unavailable")
        self._binding = binding or self._capture_binding()
        self._validate_camera_type()
        self._time_provider = time_provider or self._default_time
        self._matrix_compose = matrix_compose or _default_matrix_compose
        self._on_change = on_change
        self._owner_thread_id = threading.get_ident()
        self._handler = self._depsgraph_callback
        self._registered = False
        self._dirty = False
        self._applying = False
        self._suppressed_signature: tuple[Any, ...] | None = None
        self._failed = False
        self._last_error: CallbackErrorStatus | None = None
        self._error_count = 0

    @property
    def binding(self) -> BlenderCameraBinding:
        """固定済みbindingを返す。"""

        return self._binding

    @property
    def registered(self) -> bool:
        """callbackが登録済みかを返す。"""

        return self._registered

    @property
    def failed(self) -> bool:
        """terminal failureで隔離済みかを返す。"""

        return self._failed

    @property
    def last_error(self) -> CallbackErrorStatus | None:
        """最後に隔離したcallback例外を返す。"""

        return self._last_error

    def register(self) -> bool:
        """depsgraph handlerを一度だけ登録する。"""

        self._assert_owner_thread("register")
        self._assert_healthy("register")
        handlers = self._handler_list()
        if self._handler in handlers:
            self._registered = True
            return False
        try:
            handlers.append(self._handler)
        except BaseException as exc:
            raise BlenderCameraHostError("Blender camera callback registration failed") from exc
        self._registered = True
        return True

    def unregister(self) -> bool:
        """所有handlerを解除し、失敗時は再試行可能な状態を保つ。"""

        self._assert_owner_thread("unregister")
        handlers = self._handler_list()
        if self._handler not in handlers:
            self._registered = False
            return False
        try:
            handlers.remove(self._handler)
        except BaseException as exc:
            self._registered = self._handler in handlers
            raise BlenderCameraHostError("Blender camera callback removal failed") from exc
        self._registered = False
        self._dirty = False
        self._suppressed_signature = None
        return True

    close = unregister

    def quarantine(self) -> bool:
        """解除前でもlocal変更通知とDCC操作を停止する。"""

        self._assert_owner_thread("quarantine")
        if self._failed:
            return False
        self._failed = True
        self._dirty = False
        self._suppressed_signature = None
        return True

    def snapshot(self) -> Camera:
        """固定CameraからCommon Camera snapshotを取得する。"""

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
        """dirtyなCameraを一件だけ読み、callbackへ渡す。"""

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
            return bool(self._on_change(camera))
        except BaseException as exc:
            if not self._failed:
                self._record_error("flush", exc)
            raise BlenderCameraHostError("Blender camera flush failed") from exc

    def apply(self, camera: Camera) -> None:
        """Common Cameraを固定CameraへMain Thread上で適用する。"""

        self._assert_owner_thread("apply")
        self._assert_healthy("apply")
        if not isinstance(camera, Camera):
            raise BlenderCameraHostError("camera must be a Camera")
        self._validate_camera_type()
        self._validate_common_camera(camera)
        self._applying = True
        try:
            self._apply_transform(camera.transform)
            self._apply_shape(camera)
            self._suppressed_signature = _camera_signature(self._read_snapshot())
            self._dirty = False
        except BaseException as exc:
            self._record_error("apply", exc)
            raise BlenderCameraHostError("Blender camera apply failed") from exc
        finally:
            self._applying = False

    def _read_snapshot(self) -> Camera:
        """Blender値をmm、RH Y-up/-ZのCommon Cameraへ変換する。"""

        self._validate_camera_type()
        data = self._binding.camera_data
        projection = "orthographic" if data.type == "ORTHO" else "perspective"
        mm_per_unit = self._millimeters_per_unit()
        aspect_ratio = self._aspect_ratio()
        dof = getattr(data, "dof", None)
        use_dof = bool(getattr(dof, "use_dof", False))
        common: dict[str, Any] = {
            "entity_ref": self._binding.entity_ref,
            "transform": self._read_transform(mm_per_unit),
            "time": self._time_provider(),
            "projection": projection,
            "focal_length": None,
            "horizontal_aperture": None,
            "vertical_aperture": None,
            "aperture_offset": None,
            "clipping_range": (
                _positive(data.clip_start, "clip_start") * mm_per_unit,
                _positive(data.clip_end, "clip_end") * mm_per_unit,
            ),
            "focus_distance": _positive(dof.focus_distance, "focus_distance") * mm_per_unit if use_dof else None,
            "f_stop": _positive(dof.aperture_fstop, "aperture_fstop") if use_dof else None,
            "exposure": _optional_finite(getattr(data, "exposure", None), "exposure"),
            "orthographic_size": None,
            "film_fit": None,
            "gate_fit": None,
            "aspect_ratio": aspect_ratio,
            "change_id": uuid.uuid4().hex,
        }
        if projection == "orthographic":
            common["orthographic_size"] = _positive(data.ortho_scale, "ortho_scale") * mm_per_unit
        else:
            width = _positive(data.sensor_width, "sensor_width")
            height = _positive(data.sensor_height, "sensor_height")
            fitted_sensor = _fitted_sensor_size(data.sensor_fit, width, height)
            common.update(
                focal_length=_positive(data.lens, "lens"),
                horizontal_aperture=width,
                vertical_aperture=height,
                aperture_offset=(
                    _finite(data.shift_x, "shift_x") * fitted_sensor,
                    _finite(data.shift_y, "shift_y") * fitted_sensor,
                ),
                film_fit=_film_fit(data.sensor_fit),
            )
        return Camera(**common)

    def _read_transform(self, mm_per_unit: float) -> Transform:
        """world matrixをCommon basisのTRSへ分解する。"""

        matrix = self._binding.camera_object.matrix_world
        _validate_matrix(matrix, self._binding.camera_object)
        location, rotation, scale = matrix.decompose()
        scale_values = tuple(_positive(value, "camera scale") for value in scale)
        blender_rotation = _quaternion_xyzw(rotation)
        common_rotation = _normalized_quaternion(_quaternion_multiply(_BLENDER_TO_COMMON, blender_rotation))
        x, y, z = (_finite(value, "camera translation") * mm_per_unit for value in location)
        return Transform(
            entity_ref=self._binding.entity_ref,
            translation=(x, z, -y),
            rotation=common_rotation,
            scale=scale_values,
            coordinate_system=CoordinateSystem("world", "right", "+y", "-z", None),
            unit="millimeter",
        )

    def _apply_transform(self, transform: Transform) -> None:
        """Common basisのworld TRSをBlender RH Z-upへ戻す。"""

        mm_per_unit = self._millimeters_per_unit()
        x, y, z = transform.translation
        location = (x / mm_per_unit, -z / mm_per_unit, y / mm_per_unit)
        rotation = _normalized_quaternion(_quaternion_multiply(_COMMON_TO_BLENDER, transform.rotation))
        scale = tuple(_positive(value, "camera scale") for value in transform.scale)
        self._binding.camera_object.matrix_world = self._matrix_compose(location, rotation, scale)

    def _apply_shape(self, camera: Camera) -> None:
        """Common lens、clip、DOFをBlender Camera dataへ適用する。"""

        data = self._binding.camera_data
        mm_per_unit = self._millimeters_per_unit()
        data.type = "ORTHO" if camera.projection == "orthographic" else "PERSP"
        data.clip_start = camera.clipping_range[0] / mm_per_unit
        data.clip_end = camera.clipping_range[1] / mm_per_unit
        if camera.projection == "orthographic":
            data.ortho_scale = camera.orthographic_size / mm_per_unit
        else:
            data.lens = camera.focal_length
            data.sensor_width = camera.horizontal_aperture
            data.sensor_height = camera.vertical_aperture
            data.sensor_fit = _blender_sensor_fit(camera.film_fit)
            fitted_sensor = _fitted_sensor_size(data.sensor_fit, data.sensor_width, data.sensor_height)
            data.shift_x = camera.aperture_offset[0] / fitted_sensor
            data.shift_y = camera.aperture_offset[1] / fitted_sensor
        dof = getattr(data, "dof", None)
        if dof is not None:
            dof.use_dof = camera.focus_distance is not None or camera.f_stop is not None
            if camera.focus_distance is not None:
                dof.focus_distance = camera.focus_distance / mm_per_unit
            if camera.f_stop is not None:
                dof.aperture_fstop = camera.f_stop
        if camera.exposure is not None and hasattr(data, "exposure"):
            data.exposure = camera.exposure

    def _depsgraph_callback(self, _scene: Any, depsgraph: Any) -> None:
        """callback内では固定Cameraに関係する更新だけをdirty化する。"""

        if self._failed or self._applying:
            return
        try:
            targets = (self._binding.camera_object, self._binding.camera_data)
            for update in depsgraph.updates:
                updated = getattr(update, "id", None)
                original = getattr(updated, "original", updated)
                if any(updated is target or original is target for target in targets):
                    self._dirty = True
                    return
        except BaseException as exc:
            self._record_error("depsgraph_update_post", exc)

    def _capture_binding(self) -> BlenderCameraBinding:
        """生成時のcontext sceneとscene.cameraを固定する。"""

        scene = getattr(getattr(self._bpy, "context", None), "scene", None)
        camera_object = getattr(scene, "camera", None)
        camera_data = getattr(camera_object, "data", None)
        if scene is None or camera_object is None or camera_data is None:
            raise BlenderCameraHostUnavailableError("scene.camera is unavailable")
        pointer = getattr(camera_object, "as_pointer", None)
        identity = pointer() if callable(pointer) else id(camera_object)
        name = str(getattr(camera_object, "name_full", getattr(camera_object, "name", "Camera")))
        return BlenderCameraBinding(
            scene,
            camera_object,
            camera_data,
            EntityReference(f"blender:camera:{identity}", "camera", name, None),
        )

    def _default_time(self) -> Time:
        """Scene frameをnanosecond tickへ変換する。"""

        scene = self._binding.scene
        render = scene.render
        fps = _positive(render.fps, "fps")
        fps_base = _positive(render.fps_base, "fps_base")
        frame = _finite(scene.frame_current, "frame_current") + _finite(getattr(scene, "frame_subframe", 0.0), "frame_subframe")
        ticks = round(float(Fraction(str(frame)) * Fraction(str(fps_base)) / Fraction(str(fps)) * 1_000_000_000))
        return Time(ticks, None, None, RationalRate(1_000_000_000, 1))

    def _millimeters_per_unit(self) -> float:
        """Scene unit scaleを1 Blender Unit当たりのmmへ変換する。"""

        return _positive(self._binding.scene.unit_settings.scale_length, "scale_length") * 1000.0

    def _aspect_ratio(self) -> float:
        """Render resolutionとpixel aspectから表示aspectを得る。"""

        render = self._binding.scene.render
        width = _positive(render.resolution_x, "resolution_x") * _positive(render.pixel_aspect_x, "pixel_aspect_x")
        height = _positive(render.resolution_y, "resolution_y") * _positive(render.pixel_aspect_y, "pixel_aspect_y")
        return width / height

    def _validate_camera_type(self) -> None:
        """線形投影だけを許可し、PANO等をfail closedにする。"""

        camera_type = getattr(self._binding.camera_data, "type", None)
        if camera_type not in ("PERSP", "ORTHO"):
            raise BlenderCameraHostError(f"unsupported Blender camera type: {camera_type!r}")

    def _validate_common_camera(self, camera: Camera) -> None:
        """Blenderへ損失なくapplyできるCommon Cameraだけを許可する。"""

        transform = camera.transform
        system = transform.coordinate_system
        if (
            transform.unit != "millimeter"
            or system.space != "world"
            or system.handedness != "right"
            or system.up_axis != "+y"
            or system.forward_axis != "-z"
        ):
            raise BlenderCameraHostError("camera transform must use canonical RH Y-up/-Z millimeter world space")
        for value in transform.scale:
            _positive(value, "camera scale")
        if not math.isclose(camera.aspect_ratio, self._aspect_ratio(), rel_tol=1e-9, abs_tol=0.0):
            raise BlenderCameraHostError("camera aspect_ratio must match the Blender render aspect")
        if camera.gate_fit is not None:
            raise BlenderCameraHostError("Blender Camera does not support gate_fit")
        if camera.projection == "perspective" and camera.film_fit not in (None, "horizontal", "vertical", "fill"):
            raise BlenderCameraHostError(f"unsupported lossless film_fit: {camera.film_fit!r}")
        if camera.exposure is not None and not hasattr(self._binding.camera_data, "exposure"):
            raise BlenderCameraHostError("Blender Camera exposure is unavailable")

    def _handler_list(self) -> Any:
        """depsgraph handler listを取得する。"""

        handlers = getattr(getattr(self._bpy, "app", None), "handlers", None)
        value = getattr(handlers, _DEPSGRAPH_HANDLER, None)
        if value is None or not hasattr(value, "append") or not hasattr(value, "remove"):
            raise BlenderCameraHostUnavailableError("bpy.app.handlers.depsgraph_update_post is unavailable")
        return value

    def _assert_owner_thread(self, operation: str) -> None:
        """Blender Main Thread以外からの操作を拒否する。"""

        if threading.get_ident() != self._owner_thread_id:
            raise BlenderCameraHostError(f"{operation} must run on the Blender Main Thread")

    def _assert_healthy(self, operation: str) -> None:
        """terminal failure後の同期操作を拒否する。"""

        if self._failed:
            raise BlenderCameraHostError(f"{operation} is unavailable after Camera Host failure")

    def _record_error(self, callback: str, error: BaseException) -> None:
        """例外本体を保持せずHostをterminal failureとして隔離する。"""

        self._failed = True
        self._dirty = False
        self._suppressed_signature = None
        self._error_count += 1
        try:
            message = str(error)
        except BaseException:
            message = "<unprintable exception>"
        self._last_error = CallbackErrorStatus(callback, type(error).__name__, message[:1024], self._error_count)


def _finite(value: Any, field_name: str) -> float:
    """bool以外の有限数をfloatへ変換する。"""

    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise BlenderCameraHostError(f"{field_name} must be a finite number")
    return float(value)


def _positive(value: Any, field_name: str) -> float:
    """正の有限数をfloatへ変換する。"""

    result = _finite(value, field_name)
    if result <= 0:
        raise BlenderCameraHostError(f"{field_name} must be positive")
    return result


def _optional_finite(value: Any, field_name: str) -> float | None:
    """Noneまたは有限数を返す。"""

    return None if value is None else _finite(value, field_name)


def _quaternion_xyzw(value: Any) -> tuple[float, float, float, float]:
    """Blender QuaternionをCommon xyzw順へ変換する。"""

    return tuple(_finite(getattr(value, name), "camera rotation") for name in ("x", "y", "z", "w"))  # type: ignore[return-value]


def _quaternion_multiply(left: tuple[float, ...], right: tuple[float, ...]) -> tuple[float, float, float, float]:
    """xyzw Quaternion積を返す。"""

    lx, ly, lz, lw = left
    rx, ry, rz, rw = right
    return (
        lw * rx + lx * rw + ly * rz - lz * ry,
        lw * ry - lx * rz + ly * rw + lz * rx,
        lw * rz + lx * ry - ly * rx + lz * rw,
        lw * rw - lx * rx - ly * ry - lz * rz,
    )


def _normalized_quaternion(value: tuple[float, ...]) -> tuple[float, float, float, float]:
    """丸め誤差を除いたunit Quaternionを返す。"""

    norm = math.hypot(*value)
    if not math.isfinite(norm) or norm <= 0:
        raise BlenderCameraHostError("camera rotation must be a finite quaternion")
    return tuple(component / norm for component in value)  # type: ignore[return-value]


def _validate_matrix(matrix: Any, camera_object: Any) -> None:
    """negative scaleとshearをfail closedにする。"""

    if bool(getattr(matrix, "is_negative", False)):
        raise BlenderCameraHostError("negative camera scale is unsupported")
    if bool(getattr(matrix, "has_shear", False)):
        raise BlenderCameraHostError("camera matrix shear is unsupported")
    current = camera_object
    while current is not None:
        for value in getattr(current, "scale", ()):
            _positive(value, "camera object scale")
        current = getattr(current, "parent", None)
    to_3x3 = getattr(matrix, "to_3x3", None)
    if not callable(to_3x3):
        return
    columns = to_3x3().col
    normalized = []
    for column in columns:
        length = _positive(column.length, "camera matrix column length")
        normalized.append(tuple(_finite(value, "camera matrix") / length for value in column))
    for left, right in ((0, 1), (0, 2), (1, 2)):
        if abs(sum(a * b for a, b in zip(normalized[left], normalized[right]))) > 1e-6:
            raise BlenderCameraHostError("camera matrix shear is unsupported")


def _film_fit(value: Any) -> str:
    """Blender sensor_fitをCommon film_fitへ変換する。"""

    if value == "HORIZONTAL":
        return "horizontal"
    if value == "VERTICAL":
        return "vertical"
    if value == "AUTO":
        return "fill"
    raise BlenderCameraHostError(f"unsupported Blender sensor_fit: {value!r}")


def _fitted_sensor_size(value: Any, width: Any, height: Any) -> float:
    """Blenderがlensとshiftの基準に使うsensor寸法を返す。"""

    if value == "VERTICAL":
        return _positive(height, "sensor_height")
    if value in ("AUTO", "HORIZONTAL"):
        return _positive(width, "sensor_width")
    raise BlenderCameraHostError(f"unsupported Blender sensor_fit: {value!r}")


def _camera_signature(camera: Camera) -> tuple[Any, ...]:
    """change_idとTimeを除くDCC状態比較用signatureを返す。"""

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


def _blender_sensor_fit(value: str | None) -> str:
    """Common film_fitをBlender sensor_fitへ変換する。"""

    if value in (None, "fill"):
        return "AUTO"
    if value == "horizontal":
        return "HORIZONTAL"
    if value == "vertical":
        return "VERTICAL"
    raise BlenderCameraHostError(f"unsupported film_fit: {value!r}")


def _default_matrix_compose(location: tuple[float, ...], rotation: tuple[float, ...], scale: tuple[float, ...]) -> Any:
    """mathutilsでBlender world matrixを組み立てる。"""

    if _MATRIX is None or _QUATERNION is None or _VECTOR is None:
        raise BlenderCameraHostUnavailableError("mathutils Matrix, Quaternion and Vector are unavailable")
    x, y, z, w = rotation
    return _MATRIX.LocRotScale(_VECTOR(location), _QUATERNION((w, x, y, z)), _VECTOR(scale))


__all__ = (
    "BlenderCameraBinding",
    "BlenderCameraHost",
    "BlenderCameraHostError",
    "BlenderCameraHostUnavailableError",
    "CallbackErrorStatus",
)
