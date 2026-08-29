using System;
using System.Collections.Generic;
using NUnit.Framework;

namespace YWTA.Link.Unity.Tests
{
    internal sealed class CameraSyncSessionTests
    {
        [Test]
        public void NonAuthorityRequestsThenAcceptedAppliesBeforePublish()
        {
            CameraBody baseline = Body("baseline", 0);
            var host = new CameraHostFake(baseline) { NormalizeOnApply = true };
            var transport = new CameraTransportFake("unity:test");
            var session = new CameraSyncSession(host, transport, "session", "maya:owner", 0, baseline);
            host.Current = Body("pending", 1000);

            session.Pump();
            LinkFrame request = new LinkFrame(transport.Sent[0], Array.Empty<byte>());
            transport.Incoming.Enqueue(Accepted(request.Header.message_id, "unity:test"));
            session.Pump();

            Assert.That(session.IsFailed, Is.False);
            Assert.That(transport.Sent, Has.Count.EqualTo(2));
            Assert.That(new LinkFrame(transport.Sent[1], Array.Empty<byte>()).Header.schema, Is.EqualTo(CameraSyncSession.Schema));
            Assert.That(host.Applied, Has.Count.EqualTo(1));
            session.Pump();
            Assert.That(transport.Sent, Has.Count.EqualTo(2));
        }

        [Test]
        public void OtherWinnerRollsBackAndCanRequestNewAuthority()
        {
            CameraBody baseline = Body("baseline", 0);
            var host = new CameraHostFake(baseline) { NormalizeOnApply = true };
            var transport = new CameraTransportFake("unity:test");
            var session = new CameraSyncSession(host, transport, "session", "maya:owner", 0, baseline);
            host.Current = Body("pending", 1000);
            session.Pump();
            string correlation = new LinkFrame(transport.Sent[0], Array.Empty<byte>()).Header.message_id;
            transport.Incoming.Enqueue(Accepted(correlation, "blender:other"));
            session.Pump();
            Assert.That(session.IsFailed, Is.False);
            Assert.That(host.Applied[0].change_id, Is.EqualTo("baseline"));
            session.Pump();
            Assert.That(transport.Sent, Has.Count.EqualTo(1));

            host.Current = Body("again", 2000);
            session.Pump();
            Assert.That(new LinkFrame(transport.Sent[1], Array.Empty<byte>()).Header.target, Is.EqualTo("blender:other"));
        }

        [Test]
        public void RemoteApplyUsesHostReadbackWithoutNormalizationEcho()
        {
            CameraBody baseline = Body("baseline", 0);
            var host = new CameraHostFake(baseline) { NormalizeOnApply = true };
            var transport = new CameraTransportFake("unity:test");
            var session = new CameraSyncSession(host, transport, "session", "maya:owner", 0, baseline);
            transport.Incoming.Enqueue(new LinkFrame(CameraWire.Publish("maya:owner", "remote", Body("remote", 1000.123456789)), Array.Empty<byte>()));
            session.Pump();
            Assert.That(session.IsFailed, Is.False);
            Assert.That(transport.Sent, Is.Empty);
        }

        [Test]
        public void ExistingSnapshotReconcilesBufferedAcceptedSuffix()
        {
            var core = new AuthorityChannelCore("session", "camera", "blender:one", 1);
            var frames = new List<LinkFrame>
            {
                AcceptedStep("maya:owner", "blender:one", 0, 1),
                AcceptedStep("blender:one", "houdini:two", 1, 2)
            };
            CameraSyncSession.ReconcileBootstrapAccepted(core, frames);
            Assert.That(core.Authority, Is.EqualTo("houdini:two"));
            Assert.That(core.Revision, Is.EqualTo(2));
        }

        private static LinkFrame Accepted(string correlation, string winner) => new LinkFrame(
            JsonWire.AuthorityAccepted("maya:owner", LinkProtocol.NewId(), "publish", null,
                "sync/session/control", correlation, new AuthorityHandoff { session_id = "session", channel_id = "camera",
                    current_authority = "maya:owner", next_authority = winner, expected_authority_revision = 0,
                    new_authority_revision = 1, change_id = "change" }), Array.Empty<byte>());

        private static LinkFrame AcceptedStep(string current, string next, long expected, long revision) => new LinkFrame(
            JsonWire.AuthorityAccepted(current, LinkProtocol.NewId(), "publish", null, "sync/session/control", "request-" + revision,
                new AuthorityHandoff { session_id = "session", channel_id = "camera", current_authority = current,
                    next_authority = next, expected_authority_revision = expected, new_authority_revision = revision,
                    change_id = "change-" + revision }), Array.Empty<byte>());

        private static CameraBody Body(string change, double x)
        {
            var entity = new CameraEntityRef { entity_id = "camera", kind = "camera", display_name = "Camera" };
            return new CameraBody { entity_ref = entity, transform = new CameraTransform { entity_ref = entity,
                translation = new[] { x, 0.0, 0.0 }, rotation = new[] { 0.0, 0.0, 0.0, 1.0 }, scale = new[] { 1.0, 1.0, 1.0 },
                coordinate_system = new CameraCoordinateSystem { space = "world", handedness = "right", up_axis = "+y", forward_axis = "-z" }, unit = "millimeter" },
                time = new TimeValue { time = 0, timebase = new RationalRate { rate_num = 120000, rate_den = 1 } }, projection = "orthographic",
                clipping_range = new[] { 100.0, 10000.0 }, orthographic_size = 2000, aspect_ratio = 1, change_id = change };
        }

        private sealed class CameraHostFake : ICameraHost
        {
            internal CameraHostFake(CameraBody current) { Current = current; }
            internal CameraBody Current; internal readonly List<CameraBody> Applied = new List<CameraBody>(); internal bool NormalizeOnApply;
            public CameraBody Snapshot(string changeId) => Current;
            public void Apply(CameraBody camera) { Applied.Add(camera); Current = camera; if (NormalizeOnApply) { Current = Body(camera.change_id, (float)camera.transform.translation[0]); Current.entity_ref.entity_id = "unity-local"; Current.transform.entity_ref = Current.entity_ref; } }
        }

        private sealed class CameraTransportFake : ILinkTransport
        {
            internal CameraTransportFake(string peer) { PeerId = peer; }
            public string PeerId { get; }
            public string Failure => null;
            public bool IsFailed => false;
            internal readonly Queue<LinkFrame> Incoming = new Queue<LinkFrame>();
            internal readonly List<string> Sent = new List<string>();
            public void Connect() { }
            public void StartReceiving() { }
            public bool TryDequeue(out LinkFrame frame) { if (Incoming.Count == 0) { frame = default; return false; } frame = Incoming.Dequeue(); return true; }
            public void SendRoute(string type, string room, string topic = null) { }
            public string SendSlotJoin() => throw new NotSupportedException();
            public string SendAuthoritySnapshotRequest(string target, string sessionId) => throw new NotSupportedException();
            public void SendJson(string json) { Sent.Add(json); }
            public LinkFrame ReceiveBootstrap() => throw new NotSupportedException();
            public bool Close() => true;
        }
    }
}
