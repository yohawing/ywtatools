"""Maya Camera HostのMain Thread境界とCamera変換を検証する。"""

from __future__ import annotations

import dataclasses
import threading
import unittest

from ywta.link.camera_host import (
    MayaCameraBinding,
    MayaCameraHost,
    MayaCameraHostError,
)
from ywta_link.camera import Camera
from ywta_link.entity_ref import EntityReference
from ywta_link.time import RationalRate, Time
from ywta_link.transform import CoordinateSystem, Transform


class _Vector:
    """MVector/MQuaternionの最小fake。"""

    def __init__(self, *values):
        self.x, self.y, self.z = values[:3]
        if len(values) == 4:
            self.w = values[3]


class _Matrix:
    """world/local変換を保持する最小matrix fake。"""

    def __init__(self, translation=(1.0, 2.0, 3.0), rotation=(0.0, 0.0, 0.0, 1.0), scale=(1.0, 1.0, 1.0)):
        self.translation = translation
        self.rotation = rotation
        self.scale = scale

    def __mul__(self, _other):
        return self


class _TransformationMatrix:
    """MTransformationMatrixの最小fake。"""

    def __init__(self, matrix=None):
        self.matrix = matrix or _Matrix((0.0, 0.0, 0.0))

    def translation(self, _space):
        return _Vector(*self.matrix.translation)

    def rotation(self, asQuaternion=False):
        assert asQuaternion
        return _Vector(*self.matrix.rotation)

    def scale(self, _space):
        return self.matrix.scale

    def setTranslation(self, vector, _space):
        self.matrix.translation = (vector.x, vector.y, vector.z)

    def setRotation(self, rotation):
        self.matrix.rotation = (rotation.x, rotation.y, rotation.z, rotation.w)

    def setScale(self, scale, _space):
        self.matrix.scale = tuple(scale)

    def asMatrix(self):
        return self.matrix


class _Path:
    """MDagPathの最小fake。"""

    def __init__(self):
        self.matrix = _Matrix()
        self.parent_inverse = _Matrix((0.0, 0.0, 0.0))

    def inclusiveMatrix(self):
        return self.matrix

    def exclusiveMatrixInverse(self):
        return self.parent_inverse

    def node(self):
        return "camera-node"


class _TransformFn:
    """適用結果を保持するMFnTransform fake。"""

    def __init__(self):
        self.applied = None
        self.on_apply = None

    def setTransformation(self, transform):
        self.applied = transform.matrix
        if self.on_apply:
            self.on_apply()


class _CameraFn:
    """Camera lens属性を保持するMFnCamera fake。"""

    kHorizontalFilmFit = 1
    kVerticalFilmFit = 2
    kFillFilmFit = 3
    kOverscanFilmFit = 4

    def __init__(self, *, orthographic=False):
        self.isOrtho = orthographic
        self._near_clipping_plane = 0.1
        self._far_clipping_plane = 1000.0
        self.focusDistance = 350.0
        self.fStop = 2.8
        self.focalLength = 50.0
        self.horizontalFilmAperture = 36.0 / 25.4
        self.verticalFilmAperture = 24.0 / 25.4
        self.horizontalFilmOffset = 1.0 / 25.4
        self.verticalFilmOffset = -2.0 / 25.4
        self.filmFit = self.kHorizontalFilmFit
        self.orthoWidth = 200.0

    @property
    def nearClippingPlane(self):
        return self._near_clipping_plane

    @nearClippingPlane.setter
    def nearClippingPlane(self, value):
        if value >= self._far_clipping_plane:
            raise ValueError("near clip must remain below current far clip")
        self._near_clipping_plane = value

    @property
    def farClippingPlane(self):
        return self._far_clipping_plane

    @farClippingPlane.setter
    def farClippingPlane(self, value):
        if value <= self._near_clipping_plane:
            raise ValueError("far clip must remain above current near clip")
        self._far_clipping_plane = value

    def setNearFarClippingPlanes(self, near, far):
        if near >= far:
            raise ValueError("near clip must be below far clip")
        self._near_clipping_plane = near
        self._far_clipping_plane = far


class _DagMessage:
    callback = None

    @classmethod
    def addWorldMatrixModifiedCallback(cls, _path, callback):
        cls.callback = callback
        return "world-id"


class _NodeMessage:
    callback = None

    @classmethod
    def addAttributeChangedCallback(cls, _node, callback):
        cls.callback = callback
        return "shape-id"


class _Message:
    removed = []
    fail_ids = set()

    @classmethod
    def removeCallback(cls, callback_id):
        if callback_id in cls.fail_ids:
            raise RuntimeError("remove failed")
        cls.removed.append(callback_id)


class _Space:
    kTransform = 0


class _Api:
    """Camera Hostが使うAPI 2.0 surface。"""

    MDagMessage = _DagMessage
    MNodeMessage = _NodeMessage
    MMessage = _Message
    MSpace = _Space
    MTransformationMatrix = _TransformationMatrix
    MVector = _Vector
    MQuaternion = _Vector


def _time():
    """テスト用Common Timeを返す。"""

    return Time(1001, None, None, RationalRate(24, 1))


def _binding(*, orthographic=False, aspect_ratio=2.0):
    """固定済みactive camera bindingを作る。"""

    entity = EntityReference("maya:camera:uuid-1", "camera", "shot:renderCam", "shot")
    return MayaCameraBinding(
        camera_path=_Path(),
        transform_path=_Path(),
        camera_fn=_CameraFn(orthographic=orthographic),
        transform_fn=_TransformFn(),
        entity_ref=entity,
        aspect_ratio=aspect_ratio,
    )


def _camera(*, projection="perspective", aspect_ratio=2.0):
    """適用テスト用Common Cameraを作る。"""

    entity = EntityReference("remote:camera", "camera", "Remote", None)
    return Camera(
        entity_ref=entity,
        transform=Transform(
            entity_ref=entity,
            translation=(100.0, 200.0, 300.0),
            rotation=(0.0, 0.0, 0.0, 1.0),
            scale=(1.0, 1.0, 1.0),
            coordinate_system=CoordinateSystem("world", "right", "+y", "-z", None),
            unit="millimeter",
        ),
        time=_time(),
        projection=projection,
        focal_length=50.0 if projection == "perspective" else None,
        horizontal_aperture=36.0 if projection == "perspective" else None,
        vertical_aperture=24.0 if projection == "perspective" else None,
        aperture_offset=(1.0, -2.0) if projection == "perspective" else None,
        clipping_range=(1.0, 10000.0),
        focus_distance=3500.0,
        f_stop=2.8,
        exposure=None,
        orthographic_size=1000.0 if projection == "orthographic" else None,
        film_fit="horizontal" if projection == "perspective" else None,
        gate_fit=None,
        aspect_ratio=aspect_ratio,
        change_id="remote-change",
    )


class MayaCameraHostTests(unittest.TestCase):
    """Mayaを起動しないCamera Host contract test。"""

    def setUp(self):
        _DagMessage.callback = None
        _NodeMessage.callback = None
        _Message.removed = []
        _Message.fail_ids = set()
        self.events = []
        self.binding = _binding()
        self.host = MayaCameraHost(self.events.append, api=_Api, binding=self.binding, time_provider=_time)

    def test_binding_is_frozen_and_snapshot_uses_captured_camera(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            self.binding.aspect_ratio = 1.0

        camera = self.host.snapshot()
        self.assertIsInstance(camera, Camera)
        self.assertEqual("maya:camera:uuid-1", camera.entity_ref.entity_id)
        self.assertEqual((10.0, 20.0, 30.0), camera.transform.translation)

    def test_perspective_snapshot_converts_lengths_to_millimeters(self):
        camera = self.host.snapshot()
        self.assertEqual("perspective", camera.projection)
        self.assertEqual(50.0, camera.focal_length)
        self.assertAlmostEqual(36.0, camera.horizontal_aperture)
        self.assertAlmostEqual(1.0, camera.aperture_offset[0])
        self.assertAlmostEqual(-2.0, camera.aperture_offset[1])
        self.assertEqual((1.0, 10000.0), camera.clipping_range)
        self.assertEqual(2.0, camera.aspect_ratio)
        self.assertIsNone(camera.exposure)
        self.assertIsNone(camera.gate_fit)

    def test_orthographic_snapshot_converts_horizontal_width_to_vertical_full_height(self):
        binding = _binding(orthographic=True, aspect_ratio=2.0)
        host = MayaCameraHost(self.events.append, api=_Api, binding=binding, time_provider=_time)
        camera = host.snapshot()
        self.assertEqual("orthographic", camera.projection)
        self.assertEqual(1000.0, camera.orthographic_size)
        self.assertIsNone(camera.focal_length)

    def test_callbacks_only_mark_dirty_and_flush_coalesces_to_one_camera(self):
        self.host.register()
        _DagMessage.callback()
        _DagMessage.callback()
        _NodeMessage.callback()
        self.assertEqual([], self.events)

        self.assertTrue(self.host.flush())
        self.assertFalse(self.host.flush())
        self.assertEqual(1, len(self.events))
        self.assertIsInstance(self.events[0], Camera)

    def test_apply_uses_world_transform_and_orthographic_output_aspect_without_echo(self):
        self.host.register()
        self.binding.transform_fn.on_apply = _DagMessage.callback
        self.host.apply(_camera(projection="orthographic"))
        self.assertFalse(self.host.flush())
        self.assertEqual((10.0, 20.0, 30.0), self.binding.transform_fn.applied.translation)
        self.assertEqual(200.0, self.binding.camera_fn.orthoWidth)
        self.assertEqual([], self.events)

        _DagMessage.callback()
        self.assertFalse(self.host.flush())

    def test_apply_maps_perspective_film_fit_to_maya_enum(self):
        camera = dataclasses.replace(_camera(), film_fit="vertical")

        self.host.apply(camera)

        self.assertEqual(_CameraFn.kVerticalFilmFit, self.binding.camera_fn.filmFit)

    def test_apply_sets_near_far_atomically_when_target_near_exceeds_current_far(self):
        self.binding.camera_fn.setNearFarClippingPlanes(1.0, 10.0)
        camera = dataclasses.replace(_camera(), clipping_range=(200.0, 1000.0))

        self.host.apply(camera)

        self.assertEqual(20.0, self.binding.camera_fn.nearClippingPlane)
        self.assertEqual(100.0, self.binding.camera_fn.farClippingPlane)
        self.assertIsNotNone(self.binding.transform_fn.applied)

    def test_apply_rejects_unsupported_common_fields_before_mutation(self):
        noncanonical = dataclasses.replace(
            _camera().transform,
            coordinate_system=CoordinateSystem("world", "right", "+z", "-y", None),
        )
        cases = (
            (dataclasses.replace(_camera(), transform=noncanonical), "canonical"),
            (
                dataclasses.replace(_camera(), transform=dataclasses.replace(_camera().transform, unit="centimeter")),
                "canonical",
            ),
            (dataclasses.replace(_camera(), exposure=1.0), "exposure"),
            (dataclasses.replace(_camera(), gate_fit="fill"), "gate_fit"),
            (dataclasses.replace(_camera(projection="orthographic"), film_fit="horizontal"), "film_fit"),
        )
        for camera, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(MayaCameraHostError, message):
                    self.host.apply(camera)
                self.assertIsNone(self.binding.transform_fn.applied)

    def test_apply_preflights_missing_camera_member_before_transform_mutation(self):
        del self.binding.camera_fn.verticalFilmOffset

        with self.assertRaises(MayaCameraHostError):
            self.host.apply(_camera())

        self.assertIsNone(self.binding.transform_fn.applied)
        self.assertTrue(self.host.failed)
        self.assertIn("verticalFilmOffset", self.host.last_error.message)

    def test_apply_requires_atomic_near_far_api_before_transform_mutation(self):
        self.binding.camera_fn.setNearFarClippingPlanes = None

        with self.assertRaises(MayaCameraHostError):
            self.host.apply(_camera())

        self.assertIsNone(self.binding.transform_fn.applied)
        self.assertIn("setNearFarClippingPlanes", self.host.last_error.message)

    def test_apply_rejects_mismatched_output_aspect_before_mutation(self):
        camera = _camera(aspect_ratio=1.0)
        with self.assertRaisesRegex(MayaCameraHostError, "aspect_ratio"):
            self.host.apply(camera)
        self.assertIsNone(self.binding.transform_fn.applied)

    def test_register_unregister_are_idempotent(self):
        self.assertTrue(self.host.register())
        self.assertFalse(self.host.register())
        self.assertEqual(("world-id", "shape-id"), self.host.callback_ids)
        self.assertTrue(self.host.unregister())
        self.assertFalse(self.host.unregister())
        self.assertEqual(["world-id", "shape-id"], _Message.removed)

    def test_unregister_failure_retains_only_failed_id_for_retry(self):
        self.host.register()
        _Message.fail_ids = {"shape-id"}
        with self.assertRaises(MayaCameraHostError):
            self.host.unregister()
        self.assertEqual(("shape-id",), self.host.callback_ids)
        self.assertTrue(self.host.registered)
        _Message.fail_ids.clear()
        self.assertTrue(self.host.unregister())

    def test_flush_failure_is_terminal_and_observable(self):
        host = MayaCameraHost(
            lambda _camera: (_ for _ in ()).throw(ValueError("controller failed")),
            api=_Api,
            binding=self.binding,
            time_provider=_time,
        )
        host.register()
        _NodeMessage.callback()
        with self.assertRaises(MayaCameraHostError):
            host.flush()
        self.assertTrue(host.failed)
        self.assertEqual("ValueError", host.last_error.exception_type)
        with self.assertRaisesRegex(MayaCameraHostError, "Camera Host failure"):
            host.snapshot()

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
