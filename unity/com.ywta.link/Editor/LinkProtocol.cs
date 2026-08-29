using System;
using System.Collections.Generic;

namespace YWTA.Link.Unity
{
    internal static class LinkProtocol
    {
        internal const string PlaybackSchema = "ywta.common.playback.v1";
        internal const string SlotJoinSchema = "ywta.session.slot.join.v1";
        internal const string PeerHelloSchema = "ywta.peer.hello.v1";
        internal const string SlotDescriptorSchema = "ywta.session.slot.descriptor.v1";
        internal const string AuthorityRequestSchema = "ywta.sync.authority.request.v1";
        internal const string AuthorityAcceptedSchema = "ywta.sync.authority.accepted.v1";
        internal const string AuthorityRejectedSchema = "ywta.sync.authority.rejected.v1";
        internal const string AuthoritySnapshotRequestSchema = "ywta.sync.authority.snapshot.request.v1";
        internal const string AuthoritySnapshotSchema = "ywta.sync.authority.snapshot.v1";
        internal const string BrokerPeerId = "ywta-link:broker";
        internal const long WireTicksPerSecond = 120000;
        internal const string Room = "default";
        internal const string Topic = "playback";
        internal const string ChannelId = "playback";
        internal const string SlotId = "playback-default.v1";

        internal static string NewId()
        {
            return Guid.NewGuid().ToString("N");
        }
    }

    internal class EnvelopeHeader
    {
        public int protocol_version;
        public string message_id;
        public string type;
        public string room;
        public string sender;
        public string target;
        public string topic;
        public string correlation_id;
        public string schema;
    }

    internal sealed class RuntimeAckEnvelope : EnvelopeHeader
    {
        public string ywta_runtime_challenge;
        public string ywta_runtime_token;
    }

    internal sealed class SlotMetadata
    {
        public int contract_version;
        public string channel_id;
        public string playback_schema;
        public RationalRate wire_timebase;
    }

    internal sealed class RationalRate
    {
        public long rate_num;
        public long rate_den;
    }

    internal sealed class SlotDescriptor
    {
        public string slot_id;
        public string session_id;
        public string initial_authority;
        public SlotMetadata metadata;
        public bool created;
        public string state_peer;
    }

    internal sealed class AuthoritySnapshotRequest
    {
        public string session_id;
        public string channel_id;
    }

    internal sealed class AuthoritySnapshot
    {
        public string session_id;
        public string channel_id;
        public string authority;
        public long authority_revision;
    }

    internal sealed class AuthorityHandoff
    {
        public string session_id;
        public string channel_id;
        public string current_authority;
        public string next_authority;
        public long expected_authority_revision;
        public long new_authority_revision;
        public string change_id;
        public string reason;
    }

    internal sealed class PlaybackBody
    {
        public string state;
        public TimeValue position;
        public TimeValue playback_range;
        public double speed;
        public string direction;
        public string loop_mode;
        public string change_id;
    }

    internal sealed class TimeValue
    {
        public long time;
        public long start;
        public long end_exclusive;
        public RationalRate timebase;
    }

    internal readonly struct LinkFrame
    {
        internal LinkFrame(string json, byte[] body)
        {
            Json = json;
            Body = body;
            Root = StrictJson.ParseObject(json);
            Header = WireDecoder.Envelope(Root);
        }

        internal string Json { get; }
        internal byte[] Body { get; }
        internal Dictionary<string, object> Root { get; }
        internal EnvelopeHeader Header { get; }
    }
}
