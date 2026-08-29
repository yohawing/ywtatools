using System;
using System.Collections.Generic;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.Playables;

namespace YWTA.Link.Unity.Tests
{
    internal sealed class PlayableDirectorHostTests
    {
        private readonly List<UnityEngine.Object> _objects = new List<UnityEngine.Object>();

        [TearDown]
        public void TearDown()
        {
            foreach (UnityEngine.Object value in _objects)
            {
                UnityEngine.Object.DestroyImmediate(value);
            }

            _objects.Clear();
        }

        [Test]
        public void SelectionWinsOverMultipleLoadedDirectors()
        {
            PlayableDirector first = Director("first", 2.0);
            PlayableDirector selected = Director("selected", 2.0);

            PlayableDirector result = PlayableDirectorSelection.ResolveForTests(
                selected.gameObject,
                new[] { first, selected });

            Assert.That(result, Is.SameAs(selected));
        }

        [Test]
        public void NoSelectionRequiresExactlyOneDirector()
        {
            PlayableDirector first = Director("first", 2.0);
            PlayableDirector second = Director("second", 2.0);

            Assert.Throws<InvalidOperationException>(() =>
                PlayableDirectorSelection.ResolveForTests(null, new[] { first, second }));
            Assert.Throws<InvalidOperationException>(() =>
                PlayableDirectorSelection.ResolveForTests(null, Array.Empty<PlayableDirector>()));
            Assert.That(
                PlayableDirectorSelection.ResolveForTests(null, new[] { first }),
                Is.SameAs(first));
        }

        [Test]
        public void ApplyUsesExactPositionStateAndLoop()
        {
            PlayableDirector director = Director("director", 2.0);
            PlayableDirectorHost host = new PlayableDirectorHost(director);
            PlaybackBody playback = Playback(60000, 240000, "paused", "loop");

            host.Apply(playback);

            Assert.That(director.time, Is.EqualTo(0.5).Within(1e-9));
            Assert.That(director.state, Is.EqualTo(PlayState.Paused));
            Assert.That(director.extrapolationMode, Is.EqualTo(DirectorWrapMode.Loop));

            host.Apply(Playback(120000, 240000, "playing", "once"));
            Assert.That(director.time, Is.EqualTo(1.0).Within(1e-9));
            Assert.That(director.state, Is.EqualTo(PlayState.Playing));
            Assert.That(director.extrapolationMode, Is.EqualTo(DirectorWrapMode.Hold));
        }

        [Test]
        public void DifferingDurationAndPingPongFailBeforeMutation()
        {
            PlayableDirector director = Director("director", 2.0);
            director.time = 0.25;
            PlayableDirectorHost host = new PlayableDirectorHost(director);

            Assert.Throws<NotSupportedException>(() => host.Apply(Playback(60000, 120000, "paused", "loop")));
            Assert.That(director.time, Is.EqualTo(0.25).Within(1e-9));

            Assert.Throws<NotSupportedException>(() => host.Apply(Playback(60000, 240000, "paused", "ping-pong")));
            Assert.That(director.time, Is.EqualTo(0.25).Within(1e-9));
        }

        [Test]
        public void ReverseAndNonUnitSpeedAreUnsupported()
        {
            PlayableDirectorHost host = new PlayableDirectorHost(Director("director", 2.0));
            PlaybackBody reverse = Playback(0, 240000, "paused", "once");
            reverse.direction = "reverse";
            Assert.Throws<NotSupportedException>(() => host.Apply(reverse));

            PlaybackBody fast = Playback(0, 240000, "paused", "once");
            fast.speed = 2.0;
            Assert.Throws<NotSupportedException>(() => host.Apply(fast));
        }

        [Test]
        public void PlaybackWireKeepsNullableTimeShape()
        {
            string json = JsonWire.Playback("unity:test", "message", Playback(100, 240000, "playing", "once"));

            StringAssert.Contains("\"time\":100,\"start\":null,\"end_exclusive\":null", json);
            StringAssert.Contains("\"time\":null,\"start\":0,\"end_exclusive\":240000", json);
            StringAssert.Contains("\"schema\":\"ywta.common.playback.v1\"", json);

            PlaybackBody decoded = WireDecoder.Playback(new LinkFrame(json, Array.Empty<byte>()));
            Assert.That(decoded.position.time, Is.EqualTo(100));
            Assert.That(decoded.position.timebase.rate_num, Is.EqualTo(120000));
        }

        [Test]
        public void StrictDecoderRejectsMissingUnknownNullAndUnsafeIntegerFields()
        {
            string valid = JsonWire.Playback("unity:test", "message", Playback(100, 240000, "playing", "once"));
            Assert.Throws<FormatException>(() => WireDecoder.Playback(new LinkFrame(
                valid.Replace("\"speed\":1", "\"speed\":null"), Array.Empty<byte>())));
            Assert.Throws<FormatException>(() => WireDecoder.Playback(new LinkFrame(
                valid.Replace("\"change_id\":\"change\"", "\"change_id\":\"change\",\"extra\":0"), Array.Empty<byte>())));
            Assert.Throws<FormatException>(() => WireDecoder.Playback(new LinkFrame(
                valid.Replace("\"time\":100", "\"time\":9007199254740992"), Array.Empty<byte>())));
            Assert.Throws<FormatException>(() => WireDecoder.Playback(new LinkFrame(
                valid.Replace(",\"speed\":1", string.Empty), Array.Empty<byte>())));
        }

        [Test]
        public void StrictJsonAcceptsEscapedUnicodeSurrogatePair()
        {
            Dictionary<string, object> value = StrictJson.ParseObject("{\"value\":\"\\uD83D\\uDE00\"}");
            Assert.That(StrictJson.String(value, "value"), Is.EqualTo("😀"));
        }

        [Test]
        public void EnvelopeIgnoresCanonicalFixtureNote()
        {
            var frame = new LinkFrame("{\"protocol_version\":1,\"message_id\":\"m\",\"type\":\"publish\"," +
                "\"sender\":\"peer\",\"fixture_note\":\"未知Fieldは転送時に保持する\"}", Array.Empty<byte>());
            Assert.That(frame.Header.sender, Is.EqualTo("peer"));
        }

        [Test]
        public void SignedWireTickDecodesButHostRejectsUnsupportedNegativePosition()
        {
            string json = JsonWire.Playback("unity:test", "message", Playback(100, 240000, "paused", "once"))
                .Replace("\"time\":100", "\"time\":-1");
            PlaybackBody decoded = WireDecoder.Playback(new LinkFrame(json, Array.Empty<byte>()));
            Assert.That(decoded.position.time, Is.EqualTo(-1));
            Assert.Throws<InvalidOperationException>(() =>
                new PlayableDirectorHost(Director("negative", 2)).Apply(decoded));
        }

        [Test]
        public void FrameEncoderMatchesCanonicalPublishFixture()
        {
            const string json = "{\"protocol_version\":1,\"message_id\":\"message-001\",\"type\":\"publish\"," +
                "\"sender\":\"blender:peer-001\",\"room\":\"shot-010\"," +
                "\"schema\":\"ywta.sync.preview.v1\",\"body\":{\"revision\":8}}";
            const string expected = "5957544c00010000000000a600000000000000047b2270726f746f636f6c5f76657273696f6e223a312c226d6573736167655f6964223a226d6573736167652d303031222c2274797065223a227075626c697368222c2273656e646572223a22626c656e6465723a706565722d303031222c22726f6f6d223a2273686f742d303130222c22736368656d61223a22797774612e73796e632e707265766965772e7631222c22626f6479223a7b227265766973696f6e223a387d7d000102ff";
            byte[] encoded = LinkClient.EncodeFrame(json, new byte[] { 0, 1, 2, 255 });
            Assert.That(BitConverter.ToString(encoded).Replace("-", string.Empty).ToLowerInvariant(), Is.EqualTo(expected));
        }

        [Test]
        public void TickConversionAllowsOnlyIeeeRoundingAndSafeIntegers()
        {
            Assert.That(PlayableDirectorHost.ToTicks(0.5), Is.EqualTo(60000));
            Assert.Throws<NotSupportedException>(() => PlayableDirectorHost.ToTicks(1.0 / 7.0));
            Assert.Throws<InvalidOperationException>(() =>
                PlayableDirectorHost.ToTicks((StrictJson.MaxSafeInteger + 1.0) / LinkProtocol.WireTicksPerSecond));
        }

        [Test]
        public void RuntimeEndpointAcceptsOnlyNumericLoopback()
        {
            Assert.DoesNotThrow(() => RuntimeEndpoint.Parse("127.0.0.1:49152", null));
            Assert.Throws<System.IO.InvalidDataException>(() => RuntimeEndpoint.Parse("localhost:49152", null));
            Assert.Throws<System.IO.InvalidDataException>(() => RuntimeEndpoint.Parse("192.168.0.1:49152", null));
            Assert.Throws<System.IO.InvalidDataException>(() => RuntimeEndpoint.Parse("127.0.0.1:0", null));
            Assert.Throws<System.IO.InvalidDataException>(() => RuntimeEndpoint.Parse(null, null));
        }

        [Test]
        public void RuntimeTokenIsBoundedAscii()
        {
            Assert.DoesNotThrow(() => RuntimeEndpoint.ValidateToken("Abc_123-token"));
            Assert.Throws<FormatException>(() => RuntimeEndpoint.ValidateToken("token!"));
            Assert.Throws<FormatException>(() => RuntimeEndpoint.ValidateToken("日本語"));
            Assert.Throws<FormatException>(() => RuntimeEndpoint.ValidateToken(new string('a', 257)));
        }

        [Test]
        public void ClientAutoStartsBrokerAndCompletesChallenge()
        {
            string executable = Environment.GetEnvironmentVariable("YWTA_LINK_EXE");
            if (string.IsNullOrEmpty(executable))
                Assert.Ignore("YWTA_LINK_EXE is required for the Broker integration test");
            using (LinkClient client = new LinkClient("unity:test:" + LinkProtocol.NewId()))
            {
                Assert.DoesNotThrow(client.Connect);
            }
        }

        [Test]
        public void ClientProvesTrueAutostartInIsolatedRuntimeRoot()
        {
            if (string.IsNullOrEmpty(Environment.GetEnvironmentVariable("YWTA_LINK_EXE")))
                Assert.Ignore("YWTA_LINK_EXE is required for the Broker integration test");
            string root = System.IO.Path.Combine(System.IO.Path.GetTempPath(), "ywta-unity-runtime-" + Guid.NewGuid());
            RuntimeEndpoint.InstallRootOverride = root;
            RuntimeEndpoint.BrokerIdleSeconds = 1;
            try
            {
                using (var client = new LinkClient("unity:isolated:" + LinkProtocol.NewId())) client.Connect();
                Assert.That(System.IO.File.Exists(System.IO.Path.Combine(root, "runtime", "v1", "broker.json")), Is.True);
            }
            finally
            {
                RuntimeEndpoint.InstallRootOverride = null;
                RuntimeEndpoint.BrokerIdleSeconds = 30;
            }
        }

        [Test]
        public void SessionBootstrapsAndClosesAgainstBroker()
        {
            if (string.IsNullOrEmpty(Environment.GetEnvironmentVariable("YWTA_LINK_EXE")))
                Assert.Ignore("YWTA_LINK_EXE is required for the Broker integration test");
            TimelineSyncSession session = TimelineSyncSession.Start(
                new PlayableDirectorHost(Director("broker-session", 2.0)));
            session.Dispose();
            Assert.That(session.IsClosed, Is.True);
            Assert.That(session.IsFailed, Is.False);
        }

        [Test]
        public void ClientCleanupIsIdempotentBeforeConnect()
        {
            LinkClient client = new LinkClient("unity:cleanup");
            Assert.That(client.Close(), Is.True);
            Assert.That(client.Close(), Is.True);
            Assert.That(client.Failure, Is.Null);
        }

        [Test]
        public void MenuKeepsOneSimpleTimelineSyncEntry()
        {
            Assert.That(TimelineSyncMenu.MenuPath, Is.EqualTo("Tools/YWTA/Timeline Sync"));
        }

        private PlayableDirector Director(string name, double duration)
        {
            GameObject gameObject = new GameObject(name);
            _objects.Add(gameObject);
            PlayableDirector director = gameObject.AddComponent<PlayableDirector>();
            FakePlayableAsset asset = ScriptableObject.CreateInstance<FakePlayableAsset>();
            asset.Duration = duration;
            _objects.Add(asset);
            director.playableAsset = asset;
            director.extrapolationMode = DirectorWrapMode.None;
            return director;
        }

        private static PlaybackBody Playback(long position, long duration, string state, string loopMode)
        {
            return new PlaybackBody
            {
                state = state,
                position = new TimeValue
                {
                    time = position,
                    timebase = new RationalRate { rate_num = 120000, rate_den = 1 }
                },
                playback_range = new TimeValue
                {
                    start = 0,
                    end_exclusive = duration,
                    timebase = new RationalRate { rate_num = 120000, rate_den = 1 }
                },
                speed = 1.0,
                direction = "forward",
                loop_mode = loopMode,
                change_id = "change"
            };
        }

        private sealed class FakePlayableAsset : PlayableAsset
        {
            internal double Duration { get; set; }
            public override double duration => Duration;

            public override Playable CreatePlayable(PlayableGraph graph, GameObject owner)
            {
                return Playable.Create(graph);
            }
        }
    }
}
