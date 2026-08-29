using System;
using System.Collections.Generic;

namespace YWTA.Link.Unity
{
    internal static class WireDecoder
    {
        internal static EnvelopeHeader Envelope(Dictionary<string, object> root)
        {
            if (StrictJson.PositiveInteger(root, "protocol_version") != 1)
            {
                throw new FormatException("protocol_version must be 1");
            }
            EnvelopeHeader result = new EnvelopeHeader
            {
                protocol_version = 1,
                message_id = StrictJson.String(root, "message_id"),
                type = StrictJson.String(root, "type"),
                sender = StrictJson.String(root, "sender"),
                room = OptionalString(root, "room"),
                target = OptionalString(root, "target"),
                topic = OptionalString(root, "topic"),
                correlation_id = OptionalString(root, "correlation_id"),
                schema = OptionalString(root, "schema")
            };
            return result;
        }

        internal static RuntimeAckEnvelope RuntimeAck(LinkFrame frame)
        {
            EnvelopeHeader header = frame.Header;
            return new RuntimeAckEnvelope
            {
                protocol_version = header.protocol_version,
                message_id = header.message_id,
                type = header.type,
                sender = header.sender,
                correlation_id = header.correlation_id,
                ywta_runtime_challenge = StrictJson.String(frame.Root, "ywta_runtime_challenge"),
                ywta_runtime_token = StrictJson.String(frame.Root, "ywta_runtime_token")
            };
        }

        internal static SlotDescriptor SlotDescriptor(LinkFrame frame)
        {
            Dictionary<string, object> body = Body(frame);
            StrictJson.ExactFields(body, "slot_id", "session_id", "initial_authority", "metadata", "created", "state_peer");
            Dictionary<string, object> metadata = StrictJson.Object(body, "metadata");
            StrictJson.ExactFields(metadata, "contract_version", "channel_id", "playback_schema", "wire_timebase");
            return new SlotDescriptor
            {
                slot_id = StrictJson.String(body, "slot_id"),
                session_id = StrictJson.String(body, "session_id"),
                initial_authority = StrictJson.String(body, "initial_authority"),
                metadata = new SlotMetadata
                {
                    contract_version = checked((int)StrictJson.PositiveInteger(metadata, "contract_version")),
                    channel_id = StrictJson.String(metadata, "channel_id"),
                    playback_schema = StrictJson.String(metadata, "playback_schema"),
                    wire_timebase = Rate(StrictJson.Object(metadata, "wire_timebase"))
                },
                created = StrictJson.Boolean(body, "created"),
                state_peer = StrictJson.String(body, "state_peer")
            };
        }

        internal static AuthoritySnapshot AuthoritySnapshot(LinkFrame frame)
        {
            Dictionary<string, object> body = Body(frame);
            StrictJson.ExactFields(body, "session_id", "channel_id", "authority", "authority_revision");
            return new AuthoritySnapshot
            {
                session_id = StrictJson.String(body, "session_id"),
                channel_id = StrictJson.String(body, "channel_id"),
                authority = StrictJson.String(body, "authority"),
                authority_revision = StrictJson.NonNegativeInteger(body, "authority_revision")
            };
        }

        internal static AuthoritySnapshotRequest AuthoritySnapshotRequest(LinkFrame frame)
        {
            Dictionary<string, object> body = Body(frame);
            StrictJson.ExactFields(body, "session_id", "channel_id");
            return new AuthoritySnapshotRequest
            {
                session_id = StrictJson.String(body, "session_id"),
                channel_id = StrictJson.String(body, "channel_id")
            };
        }

        internal static AuthorityHandoff AuthorityHandoff(LinkFrame frame, bool accepted)
        {
            Dictionary<string, object> body = Body(frame);
            if (accepted)
            {
                StrictJson.ExactFields(body, "session_id", "channel_id", "current_authority", "next_authority",
                    "expected_authority_revision", "new_authority_revision", "change_id");
            }
            else
            {
                StrictJson.ExactFields(body, "session_id", "channel_id", "current_authority", "next_authority",
                    "expected_authority_revision", "change_id");
            }
            AuthorityHandoff result = DecodeHandoff(body);
            if (accepted)
            {
                result.new_authority_revision = StrictJson.NonNegativeInteger(body, "new_authority_revision");
                if (result.new_authority_revision != result.expected_authority_revision + 1)
                {
                    throw new FormatException("Authority revision must increment by one");
                }
            }
            return result;
        }

        internal static AuthorityHandoff AuthorityRejected(LinkFrame frame)
        {
            Dictionary<string, object> body = Body(frame);
            StrictJson.ExactFields(body, "session_id", "channel_id", "current_authority", "next_authority",
                "expected_authority_revision", "change_id", "reason");
            AuthorityHandoff result = DecodeHandoff(body);
            result.reason = StrictJson.String(body, "reason");
            return result;
        }

        internal static PlaybackBody Playback(LinkFrame frame)
        {
            Dictionary<string, object> body = Body(frame);
            StrictJson.ExactFields(body, "state", "position", "playback_range", "speed", "direction", "loop_mode", "change_id");
            string state = StrictJson.String(body, "state");
            string direction = StrictJson.String(body, "direction");
            string loop = StrictJson.String(body, "loop_mode");
            double speed = StrictJson.Number(body, "speed");
            if ((state != "playing" && state != "paused") ||
                (direction != "forward" && direction != "reverse") ||
                (loop != "once" && loop != "loop" && loop != "ping-pong") || speed <= 0)
            {
                throw new FormatException("Playback enum or speed is invalid");
            }
            return new PlaybackBody
            {
                state = state,
                position = Time(StrictJson.Object(body, "position"), true),
                playback_range = Time(StrictJson.Object(body, "playback_range"), false),
                speed = speed,
                direction = direction,
                loop_mode = loop,
                change_id = StrictJson.String(body, "change_id")
            };
        }

        internal static RuntimeManifest RuntimeManifest(string json)
        {
            Dictionary<string, object> value = StrictJson.ParseObject(json);
            StrictJson.ExactFields(value, "protocol_version", "endpoint", "pid", "token");
            if (StrictJson.PositiveInteger(value, "protocol_version") != 1)
            {
                throw new FormatException("runtime protocol_version must be 1");
            }
            return new RuntimeManifest
            {
                protocol_version = 1,
                endpoint = StrictJson.String(value, "endpoint"),
                pid = checked((int)StrictJson.PositiveInteger(value, "pid")),
                token = StrictJson.String(value, "token")
            };
        }

        internal static Dictionary<string, object> CurrentInstall(string json)
        {
            Dictionary<string, object> value = StrictJson.ParseObject(json);
            StrictJson.ExactFields(value, "protocol_version", "version", "executable");
            if (StrictJson.PositiveInteger(value, "protocol_version") != 1)
            {
                throw new FormatException("current protocol_version must be 1");
            }
            StrictJson.String(value, "version");
            StrictJson.String(value, "executable");
            return value;
        }

        private static Dictionary<string, object> Body(LinkFrame frame)
        {
            if (frame.Body.Length != 0)
            {
                throw new FormatException("JSON schema frame must not contain raw body bytes");
            }
            if (frame.Root.ContainsKey("ywta_runtime_challenge") || frame.Root.ContainsKey("ywta_runtime_token"))
                throw new FormatException("Schema frames must not contain runtime handshake fields");
            return StrictJson.Object(frame.Root, "body");
        }

        private static TimeValue Time(Dictionary<string, object> value, bool single)
        {
            StrictJson.ExactFields(value, "time", "start", "end_exclusive", "timebase", "sample_rate");
            StrictJson.Null(value, "sample_rate");
            TimeValue result = new TimeValue { timebase = Rate(StrictJson.Object(value, "timebase")) };
            if (single)
            {
                result.time = StrictJson.Integer(value, "time");
                StrictJson.Null(value, "start");
                StrictJson.Null(value, "end_exclusive");
            }
            else
            {
                StrictJson.Null(value, "time");
                result.start = StrictJson.Integer(value, "start");
                result.end_exclusive = StrictJson.Integer(value, "end_exclusive");
                if (result.end_exclusive <= result.start)
                {
                    throw new FormatException("Playback range must be non-empty");
                }
            }
            return result;
        }

        private static RationalRate Rate(Dictionary<string, object> value)
        {
            StrictJson.ExactFields(value, "rate_num", "rate_den");
            long numerator = StrictJson.PositiveInteger(value, "rate_num");
            long denominator = StrictJson.PositiveInteger(value, "rate_den");
            return new RationalRate { rate_num = numerator, rate_den = denominator };
        }

        private static AuthorityHandoff DecodeHandoff(Dictionary<string, object> body)
        {
            AuthorityHandoff result = new AuthorityHandoff
            {
                session_id = StrictJson.String(body, "session_id"),
                channel_id = StrictJson.String(body, "channel_id"),
                current_authority = StrictJson.String(body, "current_authority"),
                next_authority = StrictJson.String(body, "next_authority"),
                expected_authority_revision = StrictJson.NonNegativeInteger(body, "expected_authority_revision"),
                change_id = StrictJson.String(body, "change_id")
            };
            if (result.current_authority == result.next_authority)
                throw new FormatException("Authority handoff peers must differ");
            return result;
        }

        private static string OptionalString(Dictionary<string, object> value, string field)
        {
            return value.ContainsKey(field) ? StrictJson.String(value, field) : null;
        }
    }
}
