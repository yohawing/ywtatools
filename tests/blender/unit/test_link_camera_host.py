"""Blender Camera Hostの座標変換とcallback境界を検証する。"""

from __future__ import annotations

import dataclasses
import importlib.util
from pathlib import Path
import sys
import threading
import types
import unittest

from ywta_link.camera import Camera
from ywta_link.entity_ref import EntityReference
from ywta_link.time import RationalRate, Time
from ywta_link.transform import CoordinateSystem, Transform

_ADDON = Path(__file__).parents[3] / "blender" / "addons" / "ywtatools_addon"
if "ywtatools_addon" not in sys.modules:
    package = types.ModuleType("ywtatools_addon")
    package.__path__ = [str(_ADDON)]
    sys.modules["ywtatools_addon"] = package
for module_name in ("link_playback", "link_camera"):
    full_name = f"ywtatools_addon.{module_name}"
    if full_name in sys.modules:
        continue
    spec = importlib.util.spec_from_file_location(full_name, _ADDON / f"{module_name}.py")
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {full_name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)

_MODULE = sys.modules["ywtatools_addon.link_camera"]
BlenderCameraBinding = _MODULE.BlenderCameraBinding
BlenderCameraHost = _MODULE.BlenderCameraHost
BlenderCameraHostError = _MODULE.BlenderCameraHostError


class _Vector:
    """座標とQuaternionを表す最小fake。"""

    def __init__(self, *values):
        self.values = tuple(values)
        if len(values) == 4:
            self.x, self.y, self.z, self.w = values

    def __iter__(self):
        return iter(self.values)


class _Matrix:
    """decompose結果とlossy状態を保持するmatrix fake。"""

    def __init__(
        self,
        location=(1.0, 2.0, 3.0),
        rotation=(0.0, 0.0, 0.0, 1.0),
        scale=(1.0, 1.0, 1.0),
        *,
        negative=False,
        shear=False,
    ):
        self.location = location
        self.rotation = rotation
        self.scale = scale
        self.is_negative = negative
        self.has_shear = shear

    def decompose(self):
        return _Vector(*self.location), _Vector(*self.rotation), _Vector(*self.scale)


class _HandlerList(list):
    """解除失敗を注入できるhandler list。"""

    fail_remove = False

    def remove(self, value):
        if self.fail_remove:
            raise RuntimeError("remove failed")
        super().remove(value)


class _CameraObject:
    """matrix_world applyを観測できるCamera Object fake。"""

    def __init__(self, data, matrix=None):
        self.data = data
        self.name_full = "ShotCam"
        self._matrix_world = matrix or _Matrix()
        self.on_matrix_set = None

    def as_pointer(self):
        return 1234

    @property
    def matrix_world(self):
        return self._matrix_world

    @matrix_world.setter
    def matrix_world(self, value):
        self._matrix_world = value
        if self.on_matrix_set:
            self.on_matrix_set()


class _Scene:
    """Camera snapshotに必要なScene fake。"""

    def __init__(self, camera):
        self.camera = camera
        self.unit_settings = types.SimpleNamespace(scale_length=0.01)
        self.render = types.SimpleNamespace(
            resolution_x=1920,
            resolution_y=1080,
            pixel_aspect_x=1.0,
            pixel_aspect_y=1.0,
            fps=24,
            fps_base=1.0,
        )
        self.frame_current = 24
        self.frame_subframe = 0.0


class _Bpy:
    """依存注入用bpy fake。"""

    def __init__(self, scene):
        handlers = types.SimpleNamespace(depsgraph_update_post=_HandlerList())
        self.context = types.SimpleNamespace(scene=scene)
        self.app = types.SimpleNamespace(handlers=handlers)


def _camera_data(camera_type="PERSP"):
    """Blender Camera data fakeを作る。"""

    return types.SimpleNamespace(
        type=camera_type,
        lens=50.0,
        sensor_width=36.0,
        sensor_height=24.0,
        sensor_fit="HORIZONTAL",
        shift_x=0.1,
        shift_y=-0.25,
        clip_start=0.1,
        clip_end=1000.0,
        ortho_scale=20.0,
        exposure=1.5,
        dof=types.SimpleNamespace(use_dof=True, focus_distance=3.5, aperture_fstop=2.8),
    )


def _time():
    """固定Common Timeを返す。"""

    return Time(1_000_000_000, None, None, RationalRate(1_000_000_000, 1))


def _remote_camera(projection="perspective"):
    """apply用Common Cameraを作る。"""

    entity = EntityReference("remote:camera", "camera", "Remote", None)
    return Camera(
        entity_ref=entity,
        transform=Transform(
            entity_ref=entity,
            translation=(100.0, 200.0, 300.0),
            rotation=(0.0, 0.0, 0.0, 1.0),
            scale=(1.0, 2.0, 3.0),
            coordinate_system=CoordinateSystem("world", "right", "+y", "-z", None),
            unit="millimeter",
        ),
        time=_time(),
        projection=projection,
        focal_length=80.0 if projection == "perspective" else None,
        horizontal_aperture=40.0 if projection == "perspective" else None,
        vertical_aperture=20.0 if projection == "perspective" else None,
        aperture_offset=(4.0, -2.0) if projection == "perspective" else None,
        clipping_range=(10.0, 10000.0),
        focus_distance=500.0,
        f_stop=4.0,
        exposure=0.5,
        orthographic_size=400.0 if projection == "orthographic" else None,
        film_fit="vertical" if projection == "perspective" else None,
        gate_fit=None,
        aspect_ratio=16 / 9,
        change_id="remote-change",
    )


class BlenderCameraHostTests(unittest.TestCase):
    """Blenderを起動しないCamera Host contract test。"""

    def setUp(self):
        self.events = []
        self.data = _camera_data()
        self.object = _CameraObject(self.data)
        self.scene = _Scene(self.object)
        self.bpy = _Bpy(self.scene)
        self.composed = []

        def compose(location, rotation, scale):
            value = _Matrix(location, rotation, scale)
            self.composed.append(value)
            return value

        self.host = BlenderCameraHost(
            lambda camera: not self.events.append(camera),
            bpy_module=self.bpy,
            time_provider=_time,
            matrix_compose=compose,
        )

    def _depsgraph(self, *ids):
        return types.SimpleNamespace(updates=[types.SimpleNamespace(id=value) for value in ids])

    def test_binding_freezes_scene_camera_and_is_immutable(self):
        replacement = _CameraObject(_camera_data())
        self.scene.camera = replacement
        self.assertIs(self.object, self.host.binding.camera_object)
        self.assertEqual("blender:camera:1234", self.host.snapshot().entity_ref.entity_id)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            self.host.binding.camera_object = replacement

    def test_perspective_snapshot_converts_basis_units_lens_dof_and_aspect(self):
        camera = self.host.snapshot()
        self.assertEqual((10.0, 30.0, -20.0), camera.transform.translation)
        self.assertAlmostEqual(-(2**-0.5), camera.transform.rotation[0])
        self.assertAlmostEqual(2**-0.5, camera.transform.rotation[3])
        self.assertEqual("millimeter", camera.transform.unit)
        self.assertEqual("+y", camera.transform.coordinate_system.up_axis)
        self.assertEqual(50.0, camera.focal_length)
        self.assertEqual((3.6, -9.0), camera.aperture_offset)
        self.assertEqual((1.0, 10000.0), camera.clipping_range)
        self.assertEqual(35.0, camera.focus_distance)
        self.assertEqual(2.8, camera.f_stop)
        self.assertEqual(1.5, camera.exposure)
        self.assertAlmostEqual(16 / 9, camera.aspect_ratio)

    def test_orthographic_size_is_vertical_full_height_in_millimeters(self):
        self.data.type = "ORTHO"
        camera = self.host.snapshot()
        self.assertEqual("orthographic", camera.projection)
        self.assertEqual(200.0, camera.orthographic_size)
        self.assertIsNone(camera.focal_length)

    def test_depsgraph_only_marks_target_dirty_and_flush_coalesces(self):
        self.host.register()
        callback = self.bpy.app.handlers.depsgraph_update_post[0]
        callback(self.scene, self._depsgraph(object()))
        self.assertFalse(self.host.flush())
        callback(self.scene, self._depsgraph(self.data))
        callback(self.scene, self._depsgraph(self.object))
        self.assertTrue(self.host.flush())
        self.assertFalse(self.host.flush())
        self.assertEqual(1, len(self.events))

    def test_apply_converts_common_basis_and_suppresses_synchronous_echo(self):
        self.host.register()
        callback = self.bpy.app.handlers.depsgraph_update_post[0]
        self.object.on_matrix_set = lambda: callback(self.scene, self._depsgraph(self.object))
        self.host.apply(_remote_camera())
        callback(self.scene, self._depsgraph(self.data))
        self.assertFalse(self.host.flush())
        matrix = self.composed[-1]
        self.assertEqual((10.0, -30.0, 20.0), matrix.location)
        self.assertAlmostEqual(2**-0.5, matrix.rotation[0])
        self.assertAlmostEqual(2**-0.5, matrix.rotation[3])
        self.assertEqual((1.0, 2.0, 3.0), matrix.scale)
        self.assertEqual(80.0, self.data.lens)
        self.assertEqual((0.2, -0.1), (self.data.shift_x, self.data.shift_y))
        self.assertEqual("VERTICAL", self.data.sensor_fit)
        self.assertEqual(50.0, self.data.dof.focus_distance)

        self.data.lens = 81.0
        callback(self.scene, self._depsgraph(self.data))
        self.assertTrue(self.host.flush())

    def test_apply_orthographic_converts_vertical_full_height(self):
        self.host.apply(_remote_camera("orthographic"))
        self.assertEqual("ORTHO", self.data.type)
        self.assertEqual(40.0, self.data.ortho_scale)

    def test_apply_rejects_mismatched_render_aspect_before_mutation(self):
        camera = _remote_camera()
        self.scene.render.resolution_x = 1000
        with self.assertRaisesRegex(BlenderCameraHostError, "aspect_ratio"):
            self.host.apply(camera)
        self.assertEqual(50.0, self.data.lens)

    def test_pano_negative_scale_and_shear_fail_closed(self):
        for matrix in (_Matrix(negative=True), _Matrix(shear=True), _Matrix(scale=(-1.0, 1.0, 1.0))):
            data = _camera_data()
            obj = _CameraObject(data, matrix)
            host = BlenderCameraHost(
                lambda _camera: True,
                bpy_module=_Bpy(_Scene(obj)),
                time_provider=_time,
                matrix_compose=lambda *_args: None,
            )
            with self.assertRaises(BlenderCameraHostError):
                host.snapshot()
        with self.assertRaisesRegex(BlenderCameraHostError, "unsupported Blender camera type"):
            BlenderCameraHost(lambda _camera: True, bpy_module=_Bpy(_Scene(_CameraObject(_camera_data("PANO")))))

    def test_register_unregister_retry_and_terminal_flush_failure(self):
        self.assertTrue(self.host.register())
        self.assertFalse(self.host.register())
        handlers = self.bpy.app.handlers.depsgraph_update_post
        handlers.fail_remove = True
        with self.assertRaises(BlenderCameraHostError):
            self.host.unregister()
        self.assertTrue(self.host.registered)
        handlers.fail_remove = False
        self.assertTrue(self.host.unregister())

        failing = BlenderCameraHost(
            lambda _camera: (_ for _ in ()).throw(ValueError("controller failed")),
            bpy_module=self.bpy,
            time_provider=_time,
            matrix_compose=lambda *_args: None,
        )
        failing.register()
        self.bpy.app.handlers.depsgraph_update_post[0](self.scene, self._depsgraph(self.data))
        with self.assertRaises(BlenderCameraHostError):
            failing.flush()
        self.assertTrue(failing.failed)
        self.assertEqual("ValueError", failing.last_error.exception_type)

    def test_public_operations_reject_non_owner_thread(self):
        errors = []

        def read_from_worker():
            try:
                self.host.snapshot()
            except Exception as error:  # noqa: BLE001 - thread境界を検証する。
                errors.append(error)

        thread = threading.Thread(target=read_from_worker)
        thread.start()
        thread.join()
        self.assertEqual(1, len(errors))
        self.assertIn("Main Thread", str(errors[0]))


if __name__ == "__main__":
    unittest.main()
