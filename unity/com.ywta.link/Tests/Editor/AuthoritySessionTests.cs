using System;
using System.Collections.Generic;
using System.Threading;
using NUnit.Framework;

namespace YWTA.Link.Unity.Tests
{
    internal sealed class AuthoritySessionTests
    {
        [Test]
        public void RejectedRollsBackWithoutStoppingAndCanRequestAgain()
        {
            var events = new List<string>();
            var host = new FakeHost(events);
            var transport = new FakeTransport("unity:test", events);
            PlaybackBody baseline = Playback(10, "baseline");
            var session = Session(host, transport, baseline);

            host.Local.Enqueue(Playback(20, "pending"));
            session.Pump();
            LinkFrame request = new LinkFrame(transport.Sent[0], Array.Empty<byte>());
            transport.Incoming.Enqueue(Rejected(request.Header.message_id));
            session.Pump();

            Assert.That(session.IsFailed, Is.False);
            Assert.That(host.Applied[0], Is.SameAs(baseline));
            host.Local.Enqueue(Playback(30, "again"));
            session.Pump();
            Assert.That(transport.Sent, Has.Count.EqualTo(2));
        }

        [Test]
        public void OtherWinnerRollsBackWithoutStoppingAndBecomesNextTarget()
        {
            var events = new List<string>();
            var host = new FakeHost(events);
            var transport = new FakeTransport("unity:test", events);
            var session = Session(host, transport, Playback(10, "baseline"));
            host.Local.Enqueue(Playback(20, "pending"));
            session.Pump();
            transport.Incoming.Enqueue(Accepted("unrelated", "blender:other"));
            session.Pump();

            Assert.That(session.IsFailed, Is.False);
            host.Local.Enqueue(Playback(30, "again"));
            session.Pump();
            Assert.That(new LinkFrame(transport.Sent[1], Array.Empty<byte>()).Header.target,
                Is.EqualTo("blender:other"));
        }

        [Test]
        public void AcceptedAppliesPendingBeforePublishing()
        {
            var events = new List<string>();
            var host = new FakeHost(events);
            var transport = new FakeTransport("unity:test", events);
            var session = Session(host, transport, Playback(10, "baseline"));
            PlaybackBody pending = Playback(20, "pending");
            host.Local.Enqueue(pending);
            session.Pump();
            string requestId = new LinkFrame(transport.Sent[0], Array.Empty<byte>()).Header.message_id;
            events.Clear();
            transport.Incoming.Enqueue(Accepted(requestId, "unity:test"));
            session.Pump();

            Assert.That(host.Applied[0], Is.SameAs(pending));
            Assert.That(events, Is.EqualTo(new[] { "apply:pending", "send:" + LinkProtocol.PlaybackSchema }));
            Assert.That(session.IsFailed, Is.False);
        }

        [Test]
        public void AcceptedApplyFailureDoesNotPublishAndIsTerminal()
        {
            var events = new List<string>();
            var host = new FakeHost(events);
            var transport = new FakeTransport("unity:test", events);
            var session = Session(host, transport, Playback(10, "baseline"));
            host.Local.Enqueue(Playback(20, "pending"));
            session.Pump();
            string requestId = new LinkFrame(transport.Sent[0], Array.Empty<byte>()).Header.message_id;
            events.Clear();
            host.ThrowApply = true;
            transport.Incoming.Enqueue(Accepted(requestId, "unity:test"));
            session.Pump();

            Assert.That(session.IsFailed, Is.True);
            Assert.That(events, Is.Empty);
            Assert.That(transport.Sent, Has.Count.EqualTo(1));
        }

        [Test]
        public void CleanupRetainsLiveReceiverAndCanRetry()
        {
            using (var release = new ManualResetEventSlim())
            {
                var receiver = new Thread(release.Wait) { IsBackground = true };
                receiver.Start();
                var client = new LinkClient("unity:cleanup", join: (_, __) => false, receiver: receiver);
                Assert.That(client.Close(), Is.False);
                Assert.That(client.HasReceiver, Is.True);
                Assert.That(client.Failure, Is.Not.Null);
                release.Set();
                receiver.Join();
                Assert.That(client.Close(), Is.True);
                Assert.That(client.HasReceiver, Is.False);
            }
        }

        [Test]
        public void AssemblyReloadStyleCleanupCompletesSynchronouslyWithinBound()
        {
            var receiver = new Thread(() => Thread.Sleep(150)) { IsBackground = true };
            receiver.Start();
            var client = new LinkClient("unity:reload", receiver: receiver);
            DateTime deadline = DateTime.UtcNow.AddSeconds(1);
            bool closed;
            do { closed = client.Close(); } while (!closed && DateTime.UtcNow < deadline);
            Assert.That(closed, Is.True);
            Assert.That(client.HasReceiver, Is.False);
        }

        [Test]
        public void ActiveAuthorityRoutesFailClosedOnForbiddenFields()
        {
            AuthorityHandoff request = new AuthorityHandoff
            {
                session_id = "session", channel_id = "playback", current_authority = "unity:test",
                next_authority = "maya:requester", expected_authority_revision = 0, change_id = "change"
            };
            string handoff = JsonWire.AuthorityRequest("maya:requester", "request", "unity:test", request)
                .Replace("\"schema\":", "\"topic\":\"bad\",\"schema\":");
            AssertRouteFails(new LinkFrame(handoff, Array.Empty<byte>()), "unity:test");

            string snapshot = JsonWire.AuthoritySnapshotRequest("maya:requester", "snapshot", "unity:test", "session")
                .Replace("\"schema\":", "\"correlation_id\":\"bad\",\"schema\":");
            AssertRouteFails(new LinkFrame(snapshot, Array.Empty<byte>()), "unity:test");

            string accepted = Accepted("correlation", "blender:other").Json
                .Replace("\"topic\":", "\"target\":\"unity:test\",\"topic\":");
            AssertRouteFails(new LinkFrame(accepted, Array.Empty<byte>()), "maya:owner");

            string unknown = "{\"protocol_version\":1,\"message_id\":\"bad\",\"type\":\"publish\"," +
                "\"room\":\"default\",\"sender\":\"maya:owner\",\"topic\":\"sync/session/control\"," +
                "\"schema\":\"ywta.sync.authority.future.v2\",\"body\":{}}";
            AssertRouteFails(new LinkFrame(unknown, Array.Empty<byte>()), "maya:owner");
        }

        private static TimelineSyncSession Session(FakeHost host, FakeTransport transport, PlaybackBody baseline)
        {
            return new TimelineSyncSession(host, transport, "session", "maya:owner", 0, baseline);
        }

        private static void AssertRouteFails(LinkFrame frame, string authority)
        {
            var events = new List<string>();
            var transport = new FakeTransport("unity:test", events);
            var session = new TimelineSyncSession(new FakeHost(events), transport, "session", authority, 0,
                Playback(10, "baseline"));
            transport.Incoming.Enqueue(frame);
            session.Pump();
            Assert.That(session.IsFailed, Is.True);
        }

        private static LinkFrame Accepted(string correlation, string winner)
        {
            return new LinkFrame(JsonWire.AuthorityAccepted("maya:owner", LinkProtocol.NewId(), "publish", null,
                "sync/session/control", correlation, new AuthorityHandoff
                {
                    session_id = "session", channel_id = LinkProtocol.ChannelId,
                    current_authority = "maya:owner", next_authority = winner,
                    expected_authority_revision = 0, new_authority_revision = 1, change_id = "change"
                }), Array.Empty<byte>());
        }

        private static LinkFrame Rejected(string correlation)
        {
            string json = "{\"protocol_version\":1,\"message_id\":\"reject\",\"type\":\"response\"," +
                "\"room\":\"default\",\"sender\":\"maya:owner\",\"target\":\"unity:test\"," +
                "\"correlation_id\":\"" + correlation + "\",\"schema\":\"" +
                LinkProtocol.AuthorityRejectedSchema + "\",\"body\":{\"session_id\":\"session\"," +
                "\"channel_id\":\"playback\",\"current_authority\":\"maya:owner\"," +
                "\"next_authority\":\"unity:test\",\"expected_authority_revision\":0," +
                "\"change_id\":\"pending\",\"reason\":\"busy\"}}";
            return new LinkFrame(json, Array.Empty<byte>());
        }

        private static PlaybackBody Playback(long time, string change)
        {
            var rate = new RationalRate { rate_num = 120000, rate_den = 1 };
            return new PlaybackBody
            {
                state = "paused", position = new TimeValue { time = time, timebase = rate },
                playback_range = new TimeValue { start = 0, end_exclusive = 240000, timebase = rate },
                speed = 1, direction = "forward", loop_mode = "once", change_id = change
            };
        }

        private sealed class FakeHost : IPlaybackHost
        {
            private readonly List<string> _events;
            internal FakeHost(List<string> events) { _events = events; }
            internal Queue<PlaybackBody> Local { get; } = new Queue<PlaybackBody>();
            internal List<PlaybackBody> Applied { get; } = new List<PlaybackBody>();
            internal bool ThrowApply { get; set; }
            public PlaybackBody Snapshot() => null;
            public PlaybackBody Poll() => Local.Count == 0 ? null : Local.Dequeue();
            public void Apply(PlaybackBody playback)
            {
                if (ThrowApply) throw new InvalidOperationException("apply failed");
                Applied.Add(playback);
                _events.Add("apply:" + playback.change_id);
            }
        }

        private sealed class FakeTransport : ILinkTransport
        {
            private readonly List<string> _events;
            internal FakeTransport(string peerId, List<string> events) { PeerId = peerId; _events = events; }
            public string PeerId { get; }
            public string Failure => null;
            public bool IsFailed => false;
            internal Queue<LinkFrame> Incoming { get; } = new Queue<LinkFrame>();
            internal List<string> Sent { get; } = new List<string>();
            public bool TryDequeue(out LinkFrame frame)
            {
                if (Incoming.Count != 0) { frame = Incoming.Dequeue(); return true; }
                frame = default; return false;
            }
            public void SendJson(string json)
            {
                Sent.Add(json);
                _events.Add("send:" + new LinkFrame(json, Array.Empty<byte>()).Header.schema);
            }
            public bool Close() => true;
            public void Connect() => throw new NotSupportedException();
            public void StartReceiving() => throw new NotSupportedException();
            public void SendRoute(string type, string room, string topic = null) => throw new NotSupportedException();
            public string SendSlotJoin() => throw new NotSupportedException();
            public string SendAuthoritySnapshotRequest(string target, string sessionId) => throw new NotSupportedException();
            public LinkFrame ReceiveBootstrap() => throw new NotSupportedException();
        }
    }
}
