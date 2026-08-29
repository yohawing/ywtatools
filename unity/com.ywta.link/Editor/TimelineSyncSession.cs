using System;
using System.Collections.Generic;
using System.Text;
using System.Threading;

namespace YWTA.Link.Unity
{
    internal sealed class TimelineSyncSession : IDisposable
    {
        private readonly IPlaybackHost _host;
        private readonly ILinkTransport _client;
        private readonly string _peerId;
        private readonly int _ownerThreadId = Thread.CurrentThread.ManagedThreadId;
        private readonly List<LinkFrame> _bootstrapFrames = new List<LinkFrame>();
        private string _sessionId;
        private string _authority;
        private long _authorityRevision;
        private string _pendingRequestId;
        private PlaybackBody _pendingPlayback;
        private PlaybackBody _lastAuthoritative;
        private DateTime _pendingDeadline;
        private bool _disposed;

        internal TimelineSyncSession(IPlaybackHost host, ILinkTransport client)
        {
            _host = host ?? throw new ArgumentNullException(nameof(host));
            _client = client ?? throw new ArgumentNullException(nameof(client));
            _peerId = client.PeerId;
        }

        internal TimelineSyncSession(IPlaybackHost host, ILinkTransport client, string sessionId,
            string authority, long revision, PlaybackBody baseline) : this(host, client)
        {
            _sessionId = sessionId;
            _authority = authority;
            _authorityRevision = revision;
            _lastAuthoritative = baseline;
        }

        internal static TimelineSyncSession Start(PlayableDirectorHost host)
        {
            Exception last = null;
            for (int attempt = 0; attempt < 3; attempt++)
            {
                string peerId = "unity:" + Environment.MachineName + ":" + LinkProtocol.NewId().Substring(0, 8);
                TimelineSyncSession session = new TimelineSyncSession(host, new LinkClient(peerId));
                try
                {
                    session.Bootstrap();
                    return session;
                }
                catch (Exception exception)
                {
                    last = exception;
                    session.Dispose();
                }
            }
            throw new InvalidOperationException("YWTA Link bootstrap failed after three fresh clients", last);
        }

        internal string Failure { get; private set; }
        internal bool IsFailed => Failure != null || _client.IsFailed;
        internal bool IsClosed => _disposed;

        internal void Pump()
        {
            RequireOpen();
            if (Thread.CurrentThread.ManagedThreadId != _ownerThreadId)
            {
                throw new InvalidOperationException("Timeline Sync must be pumped on its owner thread");
            }
            if (_client.IsFailed)
            {
                Fail(_client.Failure);
                return;
            }

            int processed = 0;
            while (processed < 64 && _client.TryDequeue(out LinkFrame frame))
            {
                processed++;
                try
                {
                    HandleFrame(frame);
                }
                catch (Exception exception)
                {
                    Fail(exception.GetType().Name + ": " + exception.Message);
                    return;
                }
            }

            if (_pendingRequestId != null && DateTime.UtcNow >= _pendingDeadline)
            {
                RollbackPending("Authority handoff timed out", true);
                return;
            }

            try
            {
                PlaybackBody local = _host.Poll();
                if (local != null)
                {
                    HandleLocal(local);
                }
            }
            catch (Exception exception)
            {
                Fail(exception.GetType().Name + ": " + exception.Message);
            }
        }

        public void Dispose()
        {
            if (_disposed)
            {
                return;
            }

            if (_client.Close())
            {
                _disposed = true;
            }
            else
            {
                Failure = _client.Failure;
            }
        }

        private void Bootstrap()
        {
            _client.Connect();
            _client.SendRoute("join", LinkProtocol.Room);

            string slotRequestId = _client.SendSlotJoin();
            LinkFrame descriptorFrame = ReceiveExpected(slotRequestId, LinkProtocol.SlotDescriptorSchema,
                LinkProtocol.BrokerPeerId);
            SlotDescriptor descriptor = WireDecoder.SlotDescriptor(descriptorFrame);
            ValidateDescriptor(descriptor);
            _sessionId = descriptor.session_id;

            string controlTopic = ControlTopic;
            _client.SendRoute("subscribe", LinkProtocol.Room, controlTopic);
            if (descriptor.created)
            {
                if (descriptor.initial_authority != _peerId || descriptor.state_peer != _peerId)
                    throw new InvalidOperationException("Created Playback slot does not belong to this peer");
                _authority = _peerId;
                _authorityRevision = 0;
            }
            else
            {
                if (descriptor.state_peer == _peerId)
                    throw new InvalidOperationException("Existing Playback slot state peer must be remote");
                string snapshotRequestId = _client.SendAuthoritySnapshotRequest(descriptor.state_peer, _sessionId);
                LinkFrame snapshotFrame = ReceiveExpected(snapshotRequestId, LinkProtocol.AuthoritySnapshotSchema,
                    descriptor.state_peer);
                AuthoritySnapshot snapshot = WireDecoder.AuthoritySnapshot(snapshotFrame);
                if (snapshot == null || snapshot.session_id != _sessionId || snapshot.channel_id != LinkProtocol.ChannelId ||
                    string.IsNullOrEmpty(snapshot.authority) || snapshot.authority_revision < 0)
                {
                    throw new InvalidOperationException("Authority snapshot does not match the Playback slot");
                }

                _authority = snapshot.authority;
                _authorityRevision = snapshot.authority_revision;
                ReplayBootstrapFrames();
            }

            _client.SendRoute("subscribe", LinkProtocol.Room, LinkProtocol.Topic);
            _lastAuthoritative = _host.Snapshot();
            _client.StartReceiving();
        }

        private void HandleLocal(PlaybackBody local)
        {
            if (_authority == _peerId)
            {
                PublishPlayback(local);
                _lastAuthoritative = local;
                return;
            }

            _pendingPlayback = local;
            if (_pendingRequestId != null)
            {
                return;
            }

            _pendingRequestId = LinkProtocol.NewId();
            _pendingDeadline = DateTime.UtcNow.AddSeconds(1);
            AuthorityHandoff request = new AuthorityHandoff
            {
                session_id = _sessionId,
                channel_id = LinkProtocol.ChannelId,
                current_authority = _authority,
                next_authority = _peerId,
                expected_authority_revision = _authorityRevision,
                change_id = local.change_id
            };
            _client.SendJson(JsonWire.AuthorityRequest(_peerId, _pendingRequestId, _authority, request));
        }

        private void HandleFrame(LinkFrame frame)
        {
            EnvelopeHeader header = frame.Header;
            if (frame.Body.Length != 0 || header.room != LinkProtocol.Room)
            {
                return;
            }

            if (header.schema == LinkProtocol.PlaybackSchema && header.type == "publish" && header.topic == LinkProtocol.Topic)
            {
                if (header.sender == _peerId || header.sender != _authority)
                {
                    return;
                }

                PlaybackBody playback = WireDecoder.Playback(frame);
                _host.Apply(playback);
                _lastAuthoritative = playback;
                return;
            }

            if (header.schema == LinkProtocol.AuthoritySnapshotRequestSchema && header.type == "request" &&
                header.target == _peerId && _authority == _peerId)
            {
                if (header.topic != null || header.correlation_id != null || header.sender == _peerId)
                    throw new InvalidOperationException("Authority snapshot request routing is malformed");
                AuthoritySnapshotRequest request = WireDecoder.AuthoritySnapshotRequest(frame);
                if (request.session_id != _sessionId || request.channel_id != LinkProtocol.ChannelId)
                {
                    throw new InvalidOperationException("Authority snapshot request does not match this Session");
                }

                _client.SendJson(JsonWire.AuthoritySnapshotResponse(
                    _peerId,
                    LinkProtocol.NewId(),
                    header.sender,
                    header.message_id,
                    new AuthoritySnapshot
                    {
                        session_id = _sessionId,
                        channel_id = LinkProtocol.ChannelId,
                        authority = _authority,
                        authority_revision = _authorityRevision
                    }));
                return;
            }

            if (header.schema == LinkProtocol.AuthorityRequestSchema && header.type == "request" &&
                header.target == _peerId && _authority == _peerId)
            {
                if (header.topic != null || header.correlation_id != null || header.sender == _peerId)
                    throw new InvalidOperationException("Authority handoff request routing is malformed");
                AcceptHandoff(frame);
                return;
            }

            if (header.schema == LinkProtocol.AuthorityAcceptedSchema && header.type == "publish" &&
                header.topic == ControlTopic)
            {
                if (header.target != null || string.IsNullOrEmpty(header.correlation_id))
                    throw new InvalidOperationException("Authority accepted routing is malformed");
                ApplyAccepted(frame);
                return;
            }

            if (header.schema == LinkProtocol.AuthorityRejectedSchema && header.type == "response" &&
                header.target == _peerId && header.correlation_id == _pendingRequestId)
            {
                if (header.topic != null)
                    throw new InvalidOperationException("Authority rejected routing is malformed");
                AuthorityHandoff rejected = WireDecoder.AuthorityRejected(frame);
                if (!MatchesCurrent(rejected) || rejected.next_authority != _peerId || header.sender != _authority)
                    throw new InvalidOperationException("Authority rejected response is stale or malformed");
                RollbackPending("Authority handoff was rejected", false);
                return;
            }

            bool authoritySchema = header.schema == LinkProtocol.AuthoritySnapshotRequestSchema ||
                header.schema == LinkProtocol.AuthorityRequestSchema ||
                header.schema == LinkProtocol.AuthorityAcceptedSchema ||
                header.schema == LinkProtocol.AuthorityRejectedSchema;
            if (header.topic == ControlTopic || authoritySchema)
                throw new InvalidOperationException("Unknown Authority schema, type, or routing");
        }

        private void AcceptHandoff(LinkFrame frame)
        {
            AuthorityHandoff request = WireDecoder.AuthorityHandoff(frame, false);
            if (!MatchesCurrent(request) || request.next_authority != frame.Header.sender)
            {
                throw new InvalidOperationException("Authority handoff request is stale or malformed");
            }

            var core = CurrentAuthorityCore();
            AuthorityHandoff accepted = core.Accept(request);
            string responseId = LinkProtocol.NewId();
            _client.SendJson(JsonWire.AuthorityAccepted(
                _peerId, responseId, "response", request.next_authority, null, frame.Header.message_id, accepted));
            _client.SendJson(JsonWire.AuthorityAccepted(
                _peerId, LinkProtocol.NewId(), "publish", null, ControlTopic, frame.Header.message_id, accepted));
            _authority = core.Authority;
            _authorityRevision = core.Revision;
        }

        private void ApplyAccepted(LinkFrame frame)
        {
            AuthorityHandoff accepted = WireDecoder.AuthorityHandoff(frame, true);
            var core = CurrentAuthorityCore();
            if (frame.Header.sender != accepted.current_authority)
            {
                throw new InvalidOperationException("Authority accepted publish is stale or malformed");
            }
            core.Apply(accepted);
            _authority = core.Authority;
            _authorityRevision = core.Revision;
            if (_authority == _peerId && _pendingRequestId != null && frame.Header.correlation_id == _pendingRequestId)
            {
                PlaybackBody pending = _pendingPlayback;
                _pendingRequestId = null;
                _pendingPlayback = null;
                _host.Apply(pending);
                PublishPlayback(pending);
                _lastAuthoritative = pending;
            }
            else if (_pendingRequestId != null)
            {
                RollbackPending("Authority was granted to another peer", false);
            }
        }

        private bool MatchesCurrent(AuthorityHandoff value)
        {
            return CurrentAuthorityCore().Matches(value);
        }

        private AuthorityChannelCore CurrentAuthorityCore() =>
            new AuthorityChannelCore(_sessionId, LinkProtocol.ChannelId, _authority, _authorityRevision);

        private void PublishPlayback(PlaybackBody playback)
        {
            _client.SendJson(JsonWire.Playback(_peerId, LinkProtocol.NewId(), playback));
        }

        private void RollbackPending(string reason, bool terminal)
        {
            _pendingRequestId = null;
            _pendingPlayback = null;
            if (_lastAuthoritative != null)
            {
                _host.Apply(_lastAuthoritative);
            }
            if (terminal)
            {
                Fail(reason);
            }
        }

        private LinkFrame ReceiveExpected(string correlationId, string schema, string sender)
        {
            for (int count = 0; count < 256; count++)
            {
                LinkFrame frame = _client.ReceiveBootstrap();
                EnvelopeHeader header = frame.Header;
                if (frame.Body.Length == 0 && header.type == "response" && header.room == LinkProtocol.Room &&
                    header.sender == sender && header.target == _peerId &&
                    header.correlation_id == correlationId && header.schema == schema && header.topic == null)
                {
                    return frame;
                }

                if (_sessionId != null && frame.Body.Length == 0 && header.type == "publish" &&
                    header.room == LinkProtocol.Room && header.topic == ControlTopic &&
                    header.schema == LinkProtocol.AuthorityAcceptedSchema && header.target == null &&
                    !string.IsNullOrEmpty(header.correlation_id))
                {
                    _bootstrapFrames.Add(frame);
                    continue;
                }

                throw new InvalidOperationException("Unexpected YWTA Link bootstrap response");
            }

            throw new InvalidOperationException("Authority bootstrap buffer is full");
        }

        private void ReplayBootstrapFrames()
        {
            if (_bootstrapFrames.Count == 0) return;
            List<LinkFrame> chain = new List<LinkFrame>();
            AuthorityHandoff previous = null;
            foreach (LinkFrame frame in _bootstrapFrames)
            {
                AuthorityHandoff accepted = WireDecoder.AuthorityHandoff(frame, true);
                if (accepted.session_id != _sessionId || accepted.channel_id != LinkProtocol.ChannelId ||
                    frame.Header.sender != accepted.current_authority)
                    throw new InvalidOperationException("Buffered Accepted identity is malformed");
                if (previous != null && accepted.new_authority_revision == previous.new_authority_revision)
                {
                    LinkFrame duplicate = chain[chain.Count - 1];
                    AuthorityHandoff prior = WireDecoder.AuthorityHandoff(duplicate, true);
                    if (frame.Header.correlation_id != duplicate.Header.correlation_id ||
                        accepted.current_authority != prior.current_authority || accepted.next_authority != prior.next_authority ||
                        accepted.change_id != prior.change_id)
                        throw new InvalidOperationException("Accepted at the same revision conflicts");
                    continue;
                }
                if (previous != null && (accepted.expected_authority_revision != previous.new_authority_revision ||
                    accepted.current_authority != previous.next_authority))
                    throw new InvalidOperationException("Buffered Accepted chain has a gap");
                chain.Add(frame);
                previous = accepted;
            }
            AuthorityHandoff first = WireDecoder.AuthorityHandoff(chain[0], true);
            if (_authorityRevision < first.expected_authority_revision ||
                _authorityRevision > previous.new_authority_revision)
                throw new InvalidOperationException("Authority snapshot is outside the buffered Accepted chain");
            string snapshotAuthority = first.current_authority;
            foreach (LinkFrame frame in chain)
            {
                AuthorityHandoff accepted = WireDecoder.AuthorityHandoff(frame, true);
                if (accepted.new_authority_revision <= _authorityRevision)
                    snapshotAuthority = accepted.next_authority;
            }
            if (snapshotAuthority != _authority)
                throw new InvalidOperationException("Authority snapshot conflicts with buffered Accepted chain");
            foreach (LinkFrame frame in chain)
                if (WireDecoder.AuthorityHandoff(frame, true).new_authority_revision > _authorityRevision)
                    ApplyAccepted(frame);
            _bootstrapFrames.Clear();
        }

        private static void ValidateDescriptor(SlotDescriptor descriptor)
        {
            if (descriptor == null || descriptor.slot_id != LinkProtocol.SlotId || string.IsNullOrEmpty(descriptor.session_id) ||
                string.IsNullOrEmpty(descriptor.initial_authority) || string.IsNullOrEmpty(descriptor.state_peer) ||
                descriptor.metadata == null || descriptor.metadata.contract_version != 1 ||
                descriptor.metadata.channel_id != LinkProtocol.ChannelId ||
                descriptor.metadata.playback_schema != LinkProtocol.PlaybackSchema ||
                descriptor.metadata.wire_timebase == null ||
                descriptor.metadata.wire_timebase.rate_num != LinkProtocol.WireTicksPerSecond ||
                descriptor.metadata.wire_timebase.rate_den != 1)
            {
                throw new InvalidOperationException("Playback slot descriptor is incompatible");
            }
        }

        private string ControlTopic => "sync/" + _sessionId + "/control";

        private void Fail(string message)
        {
            Failure = message ?? "Timeline Sync failed";
        }

        private void RequireOpen()
        {
            if (_disposed)
            {
                throw new ObjectDisposedException(nameof(TimelineSyncSession));
            }
        }
    }

    internal static class JsonWire
    {
        internal static string RuntimeHello(string sender, string messageId, string challenge, string[] capabilities)
        {
            string json = "{\"protocol_version\":1,\"message_id\":" + Quote(messageId) +
                          ",\"type\":\"hello\",\"sender\":" + Quote(sender) +
                          ",\"schema\":" + Quote(LinkProtocol.PeerHelloSchema) +
                          ",\"body\":{\"peer_id\":" + Quote(sender) +
                          ",\"application\":\"Unity\",\"application_version\":" +
                          Quote(UnityEngine.Application.unityVersion) +
                          ",\"plugin_version\":\"0.1.0-preview.1\",\"protocol_versions\":[1]," +
                          "\"capabilities\":[" + string.Join(",", Array.ConvertAll(capabilities, Quote)) + "]}";
            if (challenge != null)
            {
                json += ",\"ywta_runtime_challenge\":" + Quote(challenge);
            }

            return json + "}";
        }

        internal static string Route(string sender, string messageId, string type, string room, string topic)
        {
            string json = "{\"protocol_version\":1,\"message_id\":" + Quote(messageId) +
                          ",\"type\":" + Quote(type) + ",\"room\":" + Quote(room) +
                          ",\"sender\":" + Quote(sender);
            if (topic != null)
            {
                json += ",\"topic\":" + Quote(topic);
            }

            return json + "}";
        }

        internal static string SlotJoin(string sender, string messageId)
        {
            string payload = "{\"slot_id\":" + Quote(LinkProtocol.SlotId) +
                             ",\"metadata\":{\"contract_version\":1,\"channel_id\":" +
                             Quote(LinkProtocol.ChannelId) + ",\"playback_schema\":" +
                             Quote(LinkProtocol.PlaybackSchema) +
                             ",\"wire_timebase\":{\"rate_num\":120000,\"rate_den\":1}}}";
            return Envelope(sender, messageId, "request", LinkProtocol.BrokerPeerId, null, null,
                LinkProtocol.SlotJoinSchema, payload);
        }

        internal static string AuthoritySnapshotRequest(
            string sender,
            string messageId,
            string target,
            string sessionId)
        {
            string payload = "{\"session_id\":" + Quote(sessionId) +
                             ",\"channel_id\":" + Quote(LinkProtocol.ChannelId) + "}";
            return Envelope(sender, messageId, "request", target, null, null,
                LinkProtocol.AuthoritySnapshotRequestSchema, payload);
        }

        internal static string Playback(string sender, string messageId, PlaybackBody body)
        {
            return Envelope(sender, messageId, "publish", null, LinkProtocol.Topic, null, LinkProtocol.PlaybackSchema,
                "{\"state\":" + Quote(body.state) +
                ",\"position\":{\"time\":" + body.position.time +
                ",\"start\":null,\"end_exclusive\":null,\"timebase\":{\"rate_num\":120000,\"rate_den\":1},\"sample_rate\":null}" +
                ",\"playback_range\":{\"time\":null,\"start\":" + body.playback_range.start +
                ",\"end_exclusive\":" + body.playback_range.end_exclusive +
                ",\"timebase\":{\"rate_num\":120000,\"rate_den\":1},\"sample_rate\":null}" +
                ",\"speed\":" + body.speed.ToString("R", System.Globalization.CultureInfo.InvariantCulture) +
                ",\"direction\":" + Quote(body.direction) +
                ",\"loop_mode\":" + Quote(body.loop_mode) +
                ",\"change_id\":" + Quote(body.change_id) + "}");
        }

        internal static string AuthorityRequest(string sender, string messageId, string target, AuthorityHandoff body)
        {
            return Envelope(sender, messageId, "request", target, null, null, LinkProtocol.AuthorityRequestSchema,
                AuthorityBody(body, false));
        }

        internal static string AuthorityAccepted(
            string sender,
            string messageId,
            string type,
            string target,
            string topic,
            string correlationId,
            AuthorityHandoff body)
        {
            return Envelope(sender, messageId, type, target, topic, correlationId, LinkProtocol.AuthorityAcceptedSchema,
                AuthorityBody(body, true));
        }

        internal static string AuthoritySnapshotResponse(
            string sender,
            string messageId,
            string target,
            string correlationId,
            AuthoritySnapshot body)
        {
            string payload = "{\"session_id\":" + Quote(body.session_id) +
                             ",\"channel_id\":" + Quote(body.channel_id) +
                             ",\"authority\":" + Quote(body.authority) +
                             ",\"authority_revision\":" + body.authority_revision + "}";
            return Envelope(sender, messageId, "response", target, null, correlationId,
                LinkProtocol.AuthoritySnapshotSchema, payload);
        }

        private static string AuthorityBody(AuthorityHandoff body, bool accepted)
        {
            string result = "{\"session_id\":" + Quote(body.session_id) +
                            ",\"channel_id\":" + Quote(body.channel_id) +
                            ",\"current_authority\":" + Quote(body.current_authority) +
                            ",\"next_authority\":" + Quote(body.next_authority) +
                            ",\"expected_authority_revision\":" + body.expected_authority_revision;
            if (accepted)
            {
                result += ",\"new_authority_revision\":" + body.new_authority_revision;
            }

            return result + ",\"change_id\":" + Quote(body.change_id) + "}";
        }

        private static string Envelope(
            string sender,
            string messageId,
            string type,
            string target,
            string topic,
            string correlationId,
            string schema,
            string body)
        {
            StringBuilder json = new StringBuilder(512);
            json.Append("{\"protocol_version\":1,\"message_id\":").Append(Quote(messageId));
            json.Append(",\"type\":").Append(Quote(type));
            json.Append(",\"room\":").Append(Quote(LinkProtocol.Room));
            json.Append(",\"sender\":").Append(Quote(sender));
            if (target != null)
            {
                json.Append(",\"target\":").Append(Quote(target));
            }

            if (topic != null)
            {
                json.Append(",\"topic\":").Append(Quote(topic));
            }

            if (correlationId != null)
            {
                json.Append(",\"correlation_id\":").Append(Quote(correlationId));
            }

            json.Append(",\"schema\":").Append(Quote(schema));
            json.Append(",\"body\":").Append(body).Append('}');
            return json.ToString();
        }

        private static string Quote(string value)
        {
            if (value == null)
            {
                return "null";
            }

            StringBuilder escaped = new StringBuilder(value.Length + 2).Append('"');
            foreach (char character in value)
            {
                switch (character)
                {
                    case '"': escaped.Append("\\\""); break;
                    case '\\': escaped.Append("\\\\"); break;
                    case '\b': escaped.Append("\\b"); break;
                    case '\f': escaped.Append("\\f"); break;
                    case '\n': escaped.Append("\\n"); break;
                    case '\r': escaped.Append("\\r"); break;
                    case '\t': escaped.Append("\\t"); break;
                    default:
                        if (character < 0x20)
                        {
                            escaped.Append("\\u").Append(((int)character).ToString("x4"));
                        }
                        else
                        {
                            escaped.Append(character);
                        }
                        break;
                }
            }

            return escaped.Append('"').ToString();
        }
    }
}
