using System;

namespace YWTA.Link.Unity
{
    internal sealed class AuthorityChannelCore
    {
        internal AuthorityChannelCore(string sessionId, string channelId, string authority, long revision)
        {
            SessionId = sessionId;
            ChannelId = channelId;
            Authority = authority;
            Revision = revision;
        }

        internal string SessionId { get; }
        internal string ChannelId { get; }
        internal string Authority { get; private set; }
        internal long Revision { get; private set; }

        internal bool Matches(AuthorityHandoff value)
        {
            return value != null && value.session_id == SessionId && value.channel_id == ChannelId &&
                value.current_authority == Authority && value.expected_authority_revision == Revision &&
                !string.IsNullOrEmpty(value.next_authority) && !string.IsNullOrEmpty(value.change_id);
        }

        internal AuthorityHandoff Accept(AuthorityHandoff request)
        {
            if (!Matches(request)) throw new InvalidOperationException("Authority handoff is stale");
            var accepted = new AuthorityHandoff
            {
                session_id = SessionId, channel_id = ChannelId, current_authority = Authority,
                next_authority = request.next_authority, expected_authority_revision = Revision,
                new_authority_revision = Revision + 1, change_id = request.change_id
            };
            Apply(accepted);
            return accepted;
        }

        internal void Apply(AuthorityHandoff accepted)
        {
            if (!Matches(accepted) || accepted.new_authority_revision != Revision + 1)
                throw new InvalidOperationException("Authority accepted is stale");
            Authority = accepted.next_authority;
            Revision = accepted.new_authority_revision;
        }
    }
}
