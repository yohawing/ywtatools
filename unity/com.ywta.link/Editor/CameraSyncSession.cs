using System;
using System.Collections.Generic;
using System.Text;
using System.Threading;

namespace YWTA.Link.Unity
{
    internal sealed class CameraSyncSession : IDisposable
    {
        internal const string Schema = "ywta.common.camera.v1";
        internal const string Topic = "camera";
        internal const string ChannelId = "camera";
        internal const string SlotId = "camera-default.v1";

        private readonly ICameraHost _host;
        private readonly ILinkTransport _transport;
        private readonly string _peerId;
        private readonly int _ownerThread = Thread.CurrentThread.ManagedThreadId;
        private AuthorityChannelCore _authority;
        private string _lastObserved;
        private CameraBody _lastAuthoritative;
        private CameraBody _pending;
        private string _pendingRequestId;
        private DateTime _pendingDeadline;
        private readonly List<LinkFrame> _bootstrapFrames = new List<LinkFrame>();
        private bool _disposed;

        internal CameraSyncSession(ICameraHost host, ILinkTransport transport, string sessionId,
            string authority, long revision, CameraBody baseline)
        {
            _host = host ?? throw new ArgumentNullException(nameof(host));
            _transport = transport ?? throw new ArgumentNullException(nameof(transport));
            _peerId = transport.PeerId;
            _authority = new AuthorityChannelCore(sessionId, ChannelId, authority, revision);
            _lastAuthoritative = baseline;
            _lastObserved = ObservationKey(baseline);
        }

        private CameraSyncSession(ICameraHost host, ILinkTransport transport)
        {
            _host = host; _transport = transport; _peerId = transport.PeerId;
        }

        internal static CameraSyncSession Start(UnityCameraHost host)
        {
            Exception last = null;
            for (int attempt = 0; attempt < 3; ++attempt)
            {
                string peer = "unity:" + Environment.MachineName + ":" + LinkProtocol.NewId().Substring(0, 8);
                CameraSyncSession session = new CameraSyncSession(host, new LinkClient(peer, capabilities: new[]
                { "camera.apply.v1", "camera.read.v1", "sync.authority.v1" }));
                try { session.Bootstrap(); return session; }
                catch (Exception exception) { last = exception; session.Dispose(); }
            }
            throw new InvalidOperationException("YWTA Camera Link bootstrap failed after three fresh clients", last);
        }

        internal string Failure { get; private set; }
        internal bool IsFailed => Failure != null || _transport.IsFailed;
        internal bool IsClosed => _disposed;

        internal void Pump()
        {
            if (_disposed) throw new ObjectDisposedException(nameof(CameraSyncSession));
            if (Thread.CurrentThread.ManagedThreadId != _ownerThread) throw new InvalidOperationException("Camera Sync must run on its owner thread");
            if (_transport.IsFailed) { Failure = _transport.Failure; return; }
            try
            {
                for (int count = 0; count < 64 && _transport.TryDequeue(out LinkFrame frame); ++count) Handle(frame);
                if (_pendingRequestId != null && DateTime.UtcNow >= _pendingDeadline)
                { RollbackPending(); Failure = "Camera Authority handoff timed out"; return; }
                CameraBody local = _host.Snapshot(LinkProtocol.NewId());
                string encoded = ObservationKey(local);
                if (encoded != _lastObserved)
                {
                    if (_authority.Authority == _peerId) Publish(local);
                    else
                    {
                        _pending = local;
                        if (_pendingRequestId == null)
                        {
                            _pendingRequestId = LinkProtocol.NewId(); _pendingDeadline = DateTime.UtcNow.AddSeconds(1);
                            _transport.SendJson(JsonWire.AuthorityRequest(_peerId, _pendingRequestId, _authority.Authority,
                                new AuthorityHandoff { session_id = _authority.SessionId, channel_id = ChannelId,
                                    current_authority = _authority.Authority, next_authority = _peerId,
                                    expected_authority_revision = _authority.Revision, change_id = local.change_id }));
                        }
                    }
                }
            }
            catch (Exception exception) { Failure = exception.GetType().Name + ": " + exception.Message; }
        }

        public void Dispose()
        {
            if (_disposed) return;
            if (_transport.Close()) _disposed = true; else Failure = _transport.Failure;
        }

        private void Bootstrap()
        {
            _transport.Connect();
            _transport.SendRoute("join", LinkProtocol.Room);
            string requestId = LinkProtocol.NewId();
            _transport.SendJson(CameraWire.SlotJoin(_peerId, requestId));
            LinkFrame frame = Receive(requestId, LinkProtocol.SlotDescriptorSchema, LinkProtocol.BrokerPeerId);
            CameraSlot descriptor = CameraWire.DecodeSlot(frame);
            if (descriptor.slotId != SlotId) throw new InvalidOperationException("Camera slot descriptor is incompatible");
            if (descriptor.created && (descriptor.initialAuthority != _peerId || descriptor.statePeer != _peerId))
                throw new InvalidOperationException("Created Camera slot does not belong to this peer");
            if (!descriptor.created && descriptor.statePeer == _peerId)
                throw new InvalidOperationException("Existing Camera state peer must be remote");
            string authority = descriptor.initialAuthority;
            long revision = 0;
            _authority = new AuthorityChannelCore(descriptor.sessionId, ChannelId, authority, revision);
            _transport.SendRoute("subscribe", LinkProtocol.Room, ControlTopic);
            if (!descriptor.created)
            {
                string snapshotId = LinkProtocol.NewId();
                _transport.SendJson(CameraWire.SnapshotRequest(_peerId, snapshotId, descriptor.statePeer, descriptor.sessionId));
                AuthoritySnapshot snapshot = WireDecoder.AuthoritySnapshot(Receive(snapshotId,
                    LinkProtocol.AuthoritySnapshotSchema, descriptor.statePeer));
                if (snapshot.session_id != descriptor.sessionId || snapshot.channel_id != ChannelId)
                    throw new InvalidOperationException("Camera Authority snapshot is incompatible");
                authority = snapshot.authority; revision = snapshot.authority_revision;
            }
            _authority = new AuthorityChannelCore(descriptor.sessionId, ChannelId, authority, revision);
            ReplayBootstrapAccepted();
            _transport.SendRoute("subscribe", LinkProtocol.Room, Topic);
            _lastAuthoritative = _host.Snapshot(LinkProtocol.NewId());
            _lastObserved = ObservationKey(_lastAuthoritative);
            _transport.StartReceiving();
        }

        private LinkFrame Receive(string correlation, string schema, string sender)
        {
            for (int count = 0; count < 256; ++count)
            {
                LinkFrame frame = _transport.ReceiveBootstrap(); EnvelopeHeader h = frame.Header;
                if (frame.Body.Length == 0 && h.type == "response" && h.room == LinkProtocol.Room && h.sender == sender &&
                    h.target == _peerId && h.correlation_id == correlation && h.schema == schema && h.topic == null) return frame;
                if (_authority != null && frame.Body.Length == 0 && h.type == "publish" && h.room == LinkProtocol.Room &&
                    h.topic == ControlTopic && h.schema == LinkProtocol.AuthorityAcceptedSchema && h.target == null &&
                    !string.IsNullOrEmpty(h.correlation_id)) { _bootstrapFrames.Add(frame); continue; }
                throw new InvalidOperationException("Unexpected Camera bootstrap response");
            }
            throw new InvalidOperationException("Camera bootstrap buffer is full");
        }

        private void Handle(LinkFrame frame)
        {
            EnvelopeHeader h = frame.Header;
            if (frame.Body.Length != 0 || h.room != LinkProtocol.Room) return;
            if (h.schema == Schema && h.type == "publish" && h.topic == Topic)
            {
                if (h.target != null || h.correlation_id != null) throw new InvalidOperationException("Camera publish route is malformed");
                if (h.sender == _peerId || h.sender != _authority.Authority) return;
                CameraBody body = CameraCodec.Decode(frame); ApplyAuthoritative(body); return;
            }
            if (h.schema == LinkProtocol.AuthoritySnapshotRequestSchema && h.type == "request" &&
                h.target == _peerId && _authority.Authority == _peerId)
            {
                if (h.topic != null || h.correlation_id != null || h.sender == _peerId) throw new InvalidOperationException("Camera snapshot route is malformed");
                AuthoritySnapshotRequest request = WireDecoder.AuthoritySnapshotRequest(frame);
                if (request.session_id != _authority.SessionId || request.channel_id != ChannelId) throw new InvalidOperationException("Camera snapshot request is stale");
                _transport.SendJson(JsonWire.AuthoritySnapshotResponse(_peerId, LinkProtocol.NewId(), h.sender, h.message_id,
                    new AuthoritySnapshot { session_id = _authority.SessionId, channel_id = ChannelId, authority = _authority.Authority, authority_revision = _authority.Revision }));
                return;
            }
            if (h.schema == LinkProtocol.AuthorityRequestSchema && h.type == "request" && h.target == _peerId && _authority.Authority == _peerId)
            {
                if (h.topic != null || h.correlation_id != null || h.sender == _peerId) throw new InvalidOperationException("Camera request route is malformed");
                AuthorityHandoff request = WireDecoder.AuthorityHandoff(frame, false);
                if (request.next_authority != h.sender) throw new InvalidOperationException("Camera Authority request is malformed");
                AuthorityHandoff accepted = _authority.Accept(request);
                _transport.SendJson(JsonWire.AuthorityAccepted(_peerId, LinkProtocol.NewId(), "response", request.next_authority, null, h.message_id, accepted));
                _transport.SendJson(JsonWire.AuthorityAccepted(_peerId, LinkProtocol.NewId(), "publish", null, ControlTopic, h.message_id, accepted));
                return;
            }
            if (h.schema == LinkProtocol.AuthorityAcceptedSchema && h.type == "publish" && h.topic == ControlTopic)
            {
                if (h.target != null || string.IsNullOrEmpty(h.correlation_id)) throw new InvalidOperationException("Camera Accepted route is malformed");
                AuthorityHandoff accepted = WireDecoder.AuthorityHandoff(frame, true);
                if (h.sender != accepted.current_authority) throw new InvalidOperationException("Camera Accepted sender is stale");
                _authority.Apply(accepted);
                if (_authority.Authority == _peerId && _pendingRequestId != null && h.correlation_id == _pendingRequestId)
                {
                    CameraBody pending = _pending; _pending = null; _pendingRequestId = null;
                    _host.Apply(pending);
                    Publish(pending);
                    _lastObserved = ObservationKey(_host.Snapshot(pending.change_id));
                }
                else if (_pendingRequestId != null) RollbackPending();
                return;
            }
            if (h.schema == LinkProtocol.AuthorityRejectedSchema && h.type == "response" && h.target == _peerId && h.correlation_id == _pendingRequestId)
            { if (h.topic != null || h.sender != _authority.Authority) throw new InvalidOperationException("Camera rejection route is malformed"); AuthorityHandoff rejected = WireDecoder.AuthorityRejected(frame); if (!_authority.Matches(rejected) || rejected.next_authority != _peerId) throw new InvalidOperationException("Camera rejection is stale"); RollbackPending(); return; }
            bool authoritySchema = h.schema == LinkProtocol.AuthoritySnapshotRequestSchema || h.schema == LinkProtocol.AuthorityRequestSchema || h.schema == LinkProtocol.AuthorityAcceptedSchema || h.schema == LinkProtocol.AuthorityRejectedSchema;
            if (h.topic == ControlTopic || authoritySchema) throw new InvalidOperationException("Unknown Camera Authority control message");
        }

        private void ReplayBootstrapAccepted()
        {
            ReconcileBootstrapAccepted(_authority, _bootstrapFrames);
            _bootstrapFrames.Clear();
        }

        internal static void ReconcileBootstrapAccepted(AuthorityChannelCore authority, IList<LinkFrame> frames)
        {
            var signatures = new Dictionary<long, string>();
            foreach (LinkFrame frame in frames)
            {
                AuthorityHandoff accepted = WireDecoder.AuthorityHandoff(frame, true);
                if (accepted.session_id != authority.SessionId || accepted.channel_id != ChannelId ||
                    frame.Header.sender != accepted.current_authority)
                    throw new InvalidOperationException("Buffered Camera Accepted identity is malformed");
                string signature = frame.Header.correlation_id + "|" + accepted.current_authority + "|" +
                    accepted.next_authority + "|" + accepted.change_id;
                if (signatures.TryGetValue(accepted.new_authority_revision, out string prior))
                { if (prior != signature) throw new InvalidOperationException("Buffered Camera Accepted revision conflicts"); continue; }
                signatures.Add(accepted.new_authority_revision, signature);
                if (accepted.new_authority_revision < authority.Revision) continue;
                if (accepted.new_authority_revision == authority.Revision)
                { if (accepted.next_authority != authority.Authority) throw new InvalidOperationException("Camera snapshot conflicts with Accepted history"); continue; }
                authority.Apply(accepted);
            }
        }

        private void Publish(CameraBody body)
        {
            _transport.SendJson(CameraWire.Publish(_peerId, LinkProtocol.NewId(), body));
            _lastAuthoritative = body; _lastObserved = ObservationKey(body);
        }

        private void RollbackPending()
        {
            _pending = null; _pendingRequestId = null;
            if (_lastAuthoritative != null) ApplyAuthoritative(_lastAuthoritative);
        }

        private void ApplyAuthoritative(CameraBody body)
        {
            _host.Apply(body);
            _lastAuthoritative = body;
            _lastObserved = ObservationKey(_host.Snapshot(body.change_id));
        }

        private static string ObservationKey(CameraBody body)
        {
            string change = body.change_id;
            try { body.change_id = "observation"; return CameraCodec.Encode(body); }
            finally { body.change_id = change; }
        }

        private string ControlTopic => "sync/" + _authority.SessionId + "/control";
    }

    internal sealed class CameraSlot
    {
        internal string slotId, sessionId, initialAuthority, statePeer;
        internal bool created;
    }

    internal static class CameraWire
    {
        internal static string Publish(string sender, string messageId, CameraBody body) =>
            Envelope(sender, messageId, "publish", null, CameraSyncSession.Topic, null, CameraSyncSession.Schema, CameraCodec.Encode(body));

        internal static string SlotJoin(string sender, string messageId) => Envelope(sender, messageId, "request",
            LinkProtocol.BrokerPeerId, null, null, LinkProtocol.SlotJoinSchema,
            "{\"slot_id\":\"camera-default.v1\",\"metadata\":{\"contract_version\":1,\"channel_id\":\"camera\",\"camera_schema\":\"ywta.common.camera.v1\"}}");

        internal static string SnapshotRequest(string sender, string messageId, string target, string sessionId) =>
            Envelope(sender, messageId, "request", target, null, null, LinkProtocol.AuthoritySnapshotRequestSchema,
                "{\"session_id\":" + Quote(sessionId) + ",\"channel_id\":\"camera\"}");

        internal static CameraSlot DecodeSlot(LinkFrame frame)
        {
            Dictionary<string, object> body = StrictJson.Object(frame.Root, "body");
            StrictJson.ExactFields(body, "slot_id", "session_id", "initial_authority", "metadata", "created", "state_peer");
            Dictionary<string, object> metadata = StrictJson.Object(body, "metadata");
            StrictJson.ExactFields(metadata, "contract_version", "channel_id", "camera_schema");
            if (StrictJson.PositiveInteger(metadata, "contract_version") != 1 || StrictJson.String(metadata, "channel_id") != "camera" || StrictJson.String(metadata, "camera_schema") != CameraSyncSession.Schema)
                throw new FormatException("Camera slot metadata is incompatible");
            return new CameraSlot { slotId = StrictJson.String(body, "slot_id"), sessionId = StrictJson.String(body, "session_id"),
                initialAuthority = StrictJson.String(body, "initial_authority"), statePeer = StrictJson.String(body, "state_peer"), created = StrictJson.Boolean(body, "created") };
        }

        private static string Envelope(string sender, string id, string type, string target, string topic,
            string correlation, string schema, string body)
        {
            StringBuilder b = new StringBuilder(1024).Append("{\"protocol_version\":1,\"message_id\":").Append(Quote(id)).Append(",\"type\":").Append(Quote(type)).Append(",\"room\":\"default\",\"sender\":").Append(Quote(sender));
            if (target != null) b.Append(",\"target\":").Append(Quote(target)); if (topic != null) b.Append(",\"topic\":").Append(Quote(topic)); if (correlation != null) b.Append(",\"correlation_id\":").Append(Quote(correlation));
            return b.Append(",\"schema\":").Append(Quote(schema)).Append(",\"body\":").Append(body).Append('}').ToString();
        }

        private static string Quote(string value) => "\"" + value.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"";
    }
}
