using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using UnityEditor;
using UnityEngine;
using Object = UnityEngine.Object;

namespace YWTA.Link.Unity
{
    internal interface ICameraHost
    {
        CameraBody Snapshot(string changeId);
        void Apply(CameraBody camera);
    }

    internal sealed class UnityCameraHost : ICameraHost
    {
        private const double MmPerMeter = 1000.0;
        private readonly Camera _camera;
        private string _echoChangeId;
        private string _echoFingerprint;

        internal UnityCameraHost(Camera camera) { _camera = camera != null ? camera : throw new ArgumentNullException(nameof(camera)); }

        internal CameraBody Snapshot(string changeId)
        {
            if (!_camera.orthographic && !_camera.usePhysicalProperties)
                throw new NotSupportedException("Perspective Camera Sync requires Unity Physical Camera");
            if (_camera.transform.parent != null)
                throw new NotSupportedException("Exact world-scale Camera Sync requires a root Unity Camera");
            Transform t = _camera.transform;
            if (!UnityCameraCoordinates.IsIdentityScale(t.lossyScale))
                throw new NotSupportedException("Camera Sync requires exact identity scale");
            double[] commonRotation = UnityCameraCoordinates.ToCommonRotation(t.rotation);
            string id = "unity-camera:" + _camera.GetInstanceID();
            CameraEntityRef entity = new CameraEntityRef { entity_id = id, kind = "camera", display_name = _camera.name, @namespace = null };
            bool ortho = _camera.orthographic;
            CameraBody result = new CameraBody
            {
                entity_ref = entity,
                transform = new CameraTransform { entity_ref = entity, translation = UnityCameraCoordinates.ToCommonTranslation(t.position), rotation = commonRotation, scale = new[] { 1.0, 1.0, 1.0 }, coordinate_system = CommonCoordinates(), unit = "millimeter", rotation_order = null },
                time = new TimeValue { time = 0, timebase = new RationalRate { rate_num = LinkProtocol.WireTicksPerSecond, rate_den = 1 } },
                projection = ortho ? "orthographic" : "perspective",
                focal_length = ortho ? null : (double?)_camera.focalLength,
                horizontal_aperture = ortho ? null : (double?)(_camera.sensorSize.x),
                vertical_aperture = ortho ? null : (double?)(_camera.sensorSize.y),
                aperture_offset = ortho ? null : new[] { (double)(_camera.lensShift.x * _camera.sensorSize.x), _camera.lensShift.y * _camera.sensorSize.y },
                clipping_range = new[] { _camera.nearClipPlane * MmPerMeter, _camera.farClipPlane * MmPerMeter },
                focus_distance = ortho ? null : (double?)(_camera.focusDistance * MmPerMeter),
                f_stop = ortho ? null : (double?)_camera.aperture,
                exposure = null,
                orthographic_size = ortho ? (double?)(_camera.orthographicSize * 2.0 * MmPerMeter) : null,
                film_fit = null, gate_fit = ortho ? null : GateFit(_camera.gateFit),
                aspect_ratio = _camera.aspect,
                change_id = _echoChangeId != null && _echoFingerprint == Fingerprint() ? _echoChangeId : changeId
            };
            if (result.change_id == changeId) { _echoChangeId = null; _echoFingerprint = null; }
            return result;
        }

        internal void Apply(CameraBody value)
        {
            if (value == null) throw new ArgumentNullException(nameof(value));
            value = CameraCodec.Decode(StrictJson.ParseObject(CameraCodec.Encode(value)));
            // すべてのunsupported条件をmutation前に判定する。
            if (Math.Abs(value.aspect_ratio - _camera.aspect) > 1e-6) throw new NotSupportedException("Camera output aspect differs");
            if (value.exposure.HasValue || value.film_fit != null)
                throw new NotSupportedException("Unity Camera cannot represent requested exposure or film fit exactly");
            CameraCoordinateSystem coordinates = value.transform.coordinate_system;
            if (coordinates.space != "world" || coordinates.handedness != "right" || coordinates.up_axis != "+y" ||
                coordinates.forward_axis != "-z" || coordinates.parent_entity_id != null)
                throw new NotSupportedException("Unity Camera requires Common world RH +Y/-Z coordinates");
            bool ortho = value.projection == "orthographic";
            if (ortho && (value.focus_distance.HasValue || value.f_stop.HasValue || value.gate_fit != null))
                throw new NotSupportedException("Orthographic Camera cannot preserve focus, aperture, or gate fit");
            if (!ortho && !_camera.usePhysicalProperties) throw new NotSupportedException("Perspective apply requires Physical Camera");
            if (value.transform.unit != "millimeter") throw new NotSupportedException("Unity Camera host requires millimeter transforms");
            if (!UnityCameraCoordinates.IsIdentityScale(value.transform.scale))
                throw new NotSupportedException("Camera Sync requires exact identity scale");
            if (_camera.transform.parent != null) throw new NotSupportedException("Exact world-scale Camera Sync requires a root Unity Camera");

            Vector3 position = UnityCameraCoordinates.ToUnityTranslation(value.transform.translation);
            Quaternion rotation = UnityCameraCoordinates.ToUnityRotation(value.transform.rotation);
            RequireFinite(position.x, "position"); RequireFinite(position.y, "position"); RequireFinite(position.z, "position");
            RequireFinite(rotation.x, "rotation"); RequireFinite(rotation.y, "rotation");
            RequireFinite(rotation.z, "rotation"); RequireFinite(rotation.w, "rotation");
            float near = PositiveFloat(value.clipping_range[0] / MmPerMeter, "near clip");
            float far = PositiveFloat(value.clipping_range[1] / MmPerMeter, "far clip");
            if (near >= far) throw new NotSupportedException("Camera clip range collapses after float conversion");
            float orthoSize = 0, focal = 0, sensorX = 0, sensorY = 0, shiftX = 0, shiftY = 0, focus = 0, aperture = 0;
            if (ortho) orthoSize = PositiveFloat(value.orthographic_size.Value / (2.0 * MmPerMeter), "orthographic size");
            else
            {
                focal = PositiveFloat(value.focal_length.Value, "focal length");
                sensorX = PositiveFloat(value.horizontal_aperture.Value, "horizontal aperture");
                sensorY = PositiveFloat(value.vertical_aperture.Value, "vertical aperture");
                shiftX = FiniteFloat(value.aperture_offset[0] / value.horizontal_aperture.Value, "lens shift");
                shiftY = FiniteFloat(value.aperture_offset[1] / value.vertical_aperture.Value, "lens shift");
                if (value.focus_distance.HasValue) focus = PositiveFloat(value.focus_distance.Value / MmPerMeter, "focus distance");
                if (value.f_stop.HasValue) aperture = PositiveFloat(value.f_stop.Value, "aperture");
            }
            _camera.transform.SetPositionAndRotation(position, rotation);
            _camera.orthographic = ortho;
            _camera.nearClipPlane = near;
            _camera.farClipPlane = far;
            if (ortho) _camera.orthographicSize = orthoSize;
            else
            {
                _camera.focalLength = focal;
                _camera.sensorSize = new Vector2(sensorX, sensorY);
                _camera.lensShift = new Vector2(shiftX, shiftY);
                _camera.gateFit = ParseGateFit(value.gate_fit);
                if (value.focus_distance.HasValue) _camera.focusDistance = focus;
                if (value.f_stop.HasValue) _camera.aperture = aperture;
            }
            _echoChangeId = value.change_id;
            _echoFingerprint = Fingerprint();
        }

        private string Fingerprint()
        {
            Transform t = _camera.transform;
            return string.Join("|", new[] { t.position.x, t.position.y, t.position.z, t.rotation.x, t.rotation.y,
                t.rotation.z, t.rotation.w, t.lossyScale.x, t.lossyScale.y, t.lossyScale.z, _camera.orthographic ? 1f : 0f,
                _camera.focalLength, _camera.sensorSize.x, _camera.sensorSize.y, _camera.lensShift.x, _camera.lensShift.y,
                _camera.nearClipPlane, _camera.farClipPlane, _camera.orthographicSize, _camera.aspect,
                _camera.focusDistance, _camera.aperture, (float)_camera.gateFit }.Select(v => v.ToString("R", CultureInfo.InvariantCulture)));
        }

        private static CameraCoordinateSystem CommonCoordinates() { return new CameraCoordinateSystem { space = "world", handedness = "right", up_axis = "+y", forward_axis = "-z", parent_entity_id = null }; }
        private static string GateFit(Camera.GateFitMode value) { switch (value) { case Camera.GateFitMode.Horizontal: return "horizontal"; case Camera.GateFitMode.Vertical: return "vertical"; case Camera.GateFitMode.Fill: return "fill"; case Camera.GateFitMode.Overscan: return "overscan"; default: return null; } }
        private static Camera.GateFitMode ParseGateFit(string value) { switch (value) { case null: return Camera.GateFitMode.None; case "horizontal": return Camera.GateFitMode.Horizontal; case "vertical": return Camera.GateFitMode.Vertical; case "fill": return Camera.GateFitMode.Fill; case "overscan": return Camera.GateFitMode.Overscan; default: throw new NotSupportedException("Unsupported gate fit"); } }
        private static float FiniteFloat(double value, string field) { float converted = (float)value; RequireFinite(converted, field); return converted; }
        private static float PositiveFloat(double value, string field) { float converted = FiniteFloat(value, field); if (converted <= 0) throw new NotSupportedException(field + " is not representable as a positive float"); return converted; }
        private static void RequireFinite(float value, string field) { if (float.IsNaN(value) || float.IsInfinity(value)) throw new NotSupportedException(field + " is outside Unity float range"); }
        CameraBody ICameraHost.Snapshot(string changeId) => Snapshot(changeId);
        void ICameraHost.Apply(CameraBody camera) => Apply(camera);
    }

    internal static class UnityCameraSelection
    {
        internal static Camera Resolve() { return ResolveForTests(Selection.activeObject, Resources.FindObjectsOfTypeAll<Camera>().Where(IsLoaded)); }
        internal static Camera ResolveForTests(Object selected, IEnumerable<Camera> loaded)
        {
            Camera chosen = FromSelection(selected);
            if (chosen != null)
            {
                if (!chosen.enabled || !IsLoaded(chosen))
                    throw new InvalidOperationException("Selected Camera must be enabled in a loaded Scene");
                return chosen;
            }
            foreach (Camera candidate in loaded.Where(v => v != null && v.enabled)) { if (chosen != null) throw new InvalidOperationException("Camera Sync requires a selected Camera when multiple are loaded"); chosen = candidate; }
            return chosen ?? throw new InvalidOperationException("Camera Sync could not find a loaded Camera");
        }
        private static Camera FromSelection(Object selected) { if (selected is Camera camera) return camera; if (selected is GameObject go) return go.GetComponent<Camera>(); if (selected is Component component) return component.GetComponent<Camera>(); return null; }
        private static bool IsLoaded(Camera camera) { var scene = camera.gameObject.scene; return scene.IsValid() && scene.isLoaded && !EditorUtility.IsPersistent(camera); }
    }

    internal static class UnityCameraCoordinates
    {
        private const double MmPerMeter = 1000.0;

        internal static double[] ToCommonTranslation(Vector3 value) =>
            new[] { value.x * MmPerMeter, value.y * MmPerMeter, -value.z * MmPerMeter };

        internal static Vector3 ToUnityTranslation(double[] value) =>
            new Vector3((float)(value[0] / MmPerMeter), (float)(value[1] / MmPerMeter), (float)(-value[2] / MmPerMeter));

        internal static double[] ToCommonRotation(Quaternion value) => Canonical(-value.x, -value.y, value.z, value.w);

        internal static Quaternion ToUnityRotation(double[] value)
        {
            double[] q = Canonical(-value[0], -value[1], value[2], value[3]);
            return new Quaternion((float)q[0], (float)q[1], (float)q[2], (float)q[3]);
        }

        internal static bool IsIdentityScale(Vector3 value) =>
            Mathf.Abs(value.x - 1) <= 1e-6f && Mathf.Abs(value.y - 1) <= 1e-6f && Mathf.Abs(value.z - 1) <= 1e-6f;

        internal static bool IsIdentityScale(double[] value) => value != null && value.Length == 3 &&
            Math.Abs(value[0] - 1) <= 1e-6 && Math.Abs(value[1] - 1) <= 1e-6 && Math.Abs(value[2] - 1) <= 1e-6;

        private static double[] Canonical(double x, double y, double z, double w)
        {
            double norm = Math.Sqrt(x * x + y * y + z * z + w * w);
            if (norm <= 0 || double.IsNaN(norm) || double.IsInfinity(norm)) throw new FormatException("Camera rotation is invalid");
            x /= norm; y /= norm; z /= norm; w /= norm;
            if (w < 0 || (w == 0 && (x < 0 || (x == 0 && (y < 0 || (y == 0 && z < 0))))))
            { x = -x; y = -y; z = -z; w = -w; }
            return new[] { x, y, z, w };
        }
    }
}
