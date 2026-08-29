using System;
using System.Collections.Generic;
using NUnit.Framework;
using UnityEditor;
using UnityEngine;
using UnityEngine.TestTools.Utils;

namespace YWTA.Link.Unity.Tests
{
    internal sealed class UnityCameraHostTests
    {
        private readonly List<GameObject> _objects = new List<GameObject>();

        [TearDown]
        public void TearDown()
        {
            foreach (GameObject value in _objects) UnityEngine.Object.DestroyImmediate(value);
            _objects.Clear();
        }

        [Test]
        public void PhysicalPerspectiveRoundTripsHandednessMillimetersAndEchoId()
        {
            Camera camera = NewCamera("physical");
            camera.usePhysicalProperties = true;
            camera.sensorSize = new Vector2(36, 24);
            camera.focalLength = 50;
            camera.focusDistance = 4;
            camera.aperture = 2.8f;
            camera.lensShift = new Vector2(0.1f, -0.2f);
            camera.nearClipPlane = 0.3f;
            camera.farClipPlane = 500;
            camera.transform.SetPositionAndRotation(new Vector3(1, 2, 3), Quaternion.Euler(10, 20, 30));
            UnityCameraHost host = new UnityCameraHost(camera);

            CameraBody body = host.Snapshot("local-change");
            Assert.That(body.transform.translation, Is.EqualTo(new[] { 1000.0, 2000.0, -3000.0 }));
            Assert.That(body.transform.unit, Is.EqualTo("millimeter"));
            Assert.That(body.clipping_range[0], Is.EqualTo(300).Within(1e-4));
            Assert.That(body.horizontal_aperture, Is.EqualTo(36));
            Assert.That(body.aperture_offset[0], Is.EqualTo(3.6).Within(1e-5));
            Assert.That(body.focus_distance, Is.EqualTo(4000));
            Assert.That(body.f_stop, Is.EqualTo(2.8).Within(1e-5));

            body.change_id = "remote-change";
            host.Apply(body);
            Assert.That(host.Snapshot("new-local-id").change_id, Is.EqualTo("remote-change"));
            Assert.That(camera.transform.position, Is.EqualTo(new Vector3(1, 2, 3)).Using(Vector3ComparerWithEqualsOperator.Instance));
        }

        [Test]
        public void OrthographicSizeUsesVerticalFullHeightInMillimeters()
        {
            Camera camera = NewCamera("ortho");
            camera.orthographic = true;
            camera.orthographicSize = 2.5f;
            UnityCameraHost host = new UnityCameraHost(camera);

            CameraBody body = host.Snapshot("snapshot");
            Assert.That(body.orthographic_size, Is.EqualTo(5000));
            Assert.That(body.focal_length, Is.Null);
            body.orthographic_size = 2000;
            body.change_id = "apply";
            host.Apply(body);
            Assert.That(camera.orthographicSize, Is.EqualTo(1).Within(1e-6));
        }

        [Test]
        public void UnsupportedAspectAndOpticalMetadataDoNotMutateCamera()
        {
            Camera camera = NewCamera("fail-closed");
            camera.orthographic = true;
            camera.transform.position = new Vector3(4, 5, 6);
            UnityCameraHost host = new UnityCameraHost(camera);
            CameraBody body = host.Snapshot("remote");
            body.transform.translation[0] = 99;
            body.aspect_ratio += 1;

            Assert.Throws<NotSupportedException>(() => host.Apply(body));
            Assert.That(camera.transform.position, Is.EqualTo(new Vector3(4, 5, 6)).Using(Vector3ComparerWithEqualsOperator.Instance));

            body.aspect_ratio = camera.aspect;
            body.exposure = 1;
            Assert.Throws<NotSupportedException>(() => host.Apply(body));
            Assert.That(camera.transform.position, Is.EqualTo(new Vector3(4, 5, 6)).Using(Vector3ComparerWithEqualsOperator.Instance));
        }

        [Test]
        public void NonIdentityScaleFailsBeforeMutation()
        {
            Camera camera = NewCamera("scale");
            camera.orthographic = true;
            UnityCameraHost host = new UnityCameraHost(camera);
            CameraBody body = host.Snapshot("scale-change");
            body.transform.translation[0] = 9000;
            body.transform.scale[0] = 2;

            Assert.Throws<NotSupportedException>(() => host.Apply(body));
            Assert.That(camera.transform.position, Is.EqualTo(Vector3.zero).Using(Vector3ComparerWithEqualsOperator.Instance));
            camera.transform.localScale = new Vector3(2, 1, 1);
            Assert.Throws<NotSupportedException>(() => host.Snapshot("local-scale"));
        }

        [Test]
        public void ExtremeFloatAndOrthographicOpticsFailBeforeMutation()
        {
            Camera camera = NewCamera("extreme"); camera.orthographic = true; camera.transform.position = new Vector3(4, 5, 6);
            UnityCameraHost host = new UnityCameraHost(camera); CameraBody body = host.Snapshot("remote");
            body.transform.translation[0] = 1e300;
            Assert.Throws<NotSupportedException>(() => host.Apply(body));
            Assert.That(camera.transform.position, Is.EqualTo(new Vector3(4, 5, 6)).Using(Vector3ComparerWithEqualsOperator.Instance));
            body = host.Snapshot("remote"); body.clipping_range = new[] { 1e-300, 2e-300 };
            Assert.Throws<NotSupportedException>(() => host.Apply(body));
            body = host.Snapshot("remote"); body.focus_distance = 1000; body.f_stop = 2.8; body.gate_fit = "fill";
            Assert.Throws<NotSupportedException>(() => host.Apply(body));
            Assert.That(camera.transform.position, Is.EqualTo(new Vector3(4, 5, 6)).Using(Vector3ComparerWithEqualsOperator.Instance));
        }

        [Test]
        public void MultiAxisQuaternionReflectionRoundTripsAndCanonicalizesSign()
        {
            Quaternion unity = Quaternion.Euler(90, 90, 90);
            double[] common = UnityCameraCoordinates.ToCommonRotation(unity);
            Quaternion roundTrip = UnityCameraCoordinates.ToUnityRotation(common);
            Assert.That(Mathf.Abs(Quaternion.Dot(unity.normalized, roundTrip.normalized)), Is.EqualTo(1).Within(1e-6));
            Assert.That(common[3], Is.GreaterThanOrEqualTo(0));

            double[] negated = { -common[0], -common[1], -common[2], -common[3] };
            Quaternion fromNegated = UnityCameraCoordinates.ToUnityRotation(negated);
            Assert.That(Quaternion.Dot(roundTrip, fromNegated), Is.EqualTo(1).Within(1e-6));
        }

        [Test]
        public void NonPhysicalPerspectiveIsUnsupported()
        {
            Camera camera = NewCamera("fov-only");
            camera.orthographic = false;
            camera.usePhysicalProperties = false;
            Assert.Throws<NotSupportedException>(() => new UnityCameraHost(camera).Snapshot("change"));
        }

        [Test]
        public void StrictCodecHasExactlySeventeenFieldsAndRejectsProjectionMismatch()
        {
            Camera camera = NewCamera("codec");
            camera.orthographic = true;
            CameraBody body = new UnityCameraHost(camera).Snapshot("change");
            string json = CameraCodec.Encode(body);
            Dictionary<string, object> root = StrictJson.ParseObject(json);
            Assert.That(root.Count, Is.EqualTo(17));
            Assert.That(CameraCodec.Decode(root).orthographic_size, Is.EqualTo(body.orthographic_size));
            Assert.Throws<FormatException>(() => CameraCodec.Decode(StrictJson.ParseObject(
                json.Replace("\"orthographic_size\":10000", "\"orthographic_size\":null"))));
            Assert.Throws<FormatException>(() => CameraCodec.Decode(StrictJson.ParseObject(
                json.Replace("\"change_id\":\"change\"", "\"change_id\":\"change\",\"extra\":0"))));
        }

        [Test]
        public void SelectionRequiresOneCameraUnlessSelectionWins()
        {
            Camera first = NewCamera("first");
            Camera second = NewCamera("second");
            Assert.That(UnityCameraSelection.ResolveForTests(second.gameObject, new[] { first, second }), Is.SameAs(second));
            Assert.Throws<InvalidOperationException>(() => UnityCameraSelection.ResolveForTests(null, new[] { first, second }));
            Assert.That(UnityCameraSelection.ResolveForTests(null, new[] { first }), Is.SameAs(first));
            first.enabled = false;
            Assert.Throws<InvalidOperationException>(() => UnityCameraSelection.ResolveForTests(null, new[] { first }));
            second.enabled = false;
            Assert.Throws<InvalidOperationException>(() => UnityCameraSelection.ResolveForTests(second, new[] { second }));
        }

        [Test]
        public void PersistentPrefabCameraCannotBeSelected()
        {
            const string path = "Assets/YwtaCameraSelectionTest.prefab";
            GameObject source = new GameObject("prefab-camera"); source.AddComponent<Camera>();
            try
            {
                GameObject prefab = PrefabUtility.SaveAsPrefabAsset(source, path);
                Camera persistent = prefab.GetComponent<Camera>();
                Assert.That(EditorUtility.IsPersistent(persistent), Is.True);
                Assert.Throws<InvalidOperationException>(() => UnityCameraSelection.ResolveForTests(persistent, new[] { persistent }));
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(source);
                AssetDatabase.DeleteAsset(path);
            }
        }

        [Test]
        public void CameraSessionBootstrapsAndPublishesAgainstRealBroker()
        {
            if (string.IsNullOrEmpty(Environment.GetEnvironmentVariable("YWTA_LINK_EXE")))
                Assert.Ignore("YWTA_LINK_EXE is required for the Broker integration test");
            Camera camera = NewCamera("broker-camera");
            camera.orthographic = true;
            CameraSyncSession session = CameraSyncSession.Start(new UnityCameraHost(camera));
            camera.transform.position = new Vector3(1, 2, 3);
            session.Pump();
            Assert.That(session.IsFailed, Is.False);
            session.Dispose();
            Assert.That(session.IsClosed, Is.True);
        }

        [Test]
        public void CameraMenuKeepsOneSimpleToggleEntry()
        {
            Assert.That(CameraSyncMenu.MenuPath, Is.EqualTo("Tools/YWTA/Camera Sync"));
        }

        private Camera NewCamera(string name)
        {
            GameObject value = new GameObject(name);
            _objects.Add(value);
            Camera camera = value.AddComponent<Camera>();
            camera.aspect = 16.0f / 9.0f;
            return camera;
        }
    }
}
