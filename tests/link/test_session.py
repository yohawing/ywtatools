"""Sync SessionのAuthority/content revision境界を検証する。"""

from __future__ import annotations

import unittest

from ywta_link.errors import AuthorityViolation, StaleRevision, ValidationError
from ywta_link.session import ChannelRevisionTracker


class ChannelRevisionTrackerTest(unittest.TestCase):
    """Authority変更とcontent sender validationの共有境界を検証する。"""

    def test_mapping_channel_ids_and_authorities_are_strict_utf8_identifiers(self) -> None:
        """mappingのChannel IDとAuthorityを非空白UTF-8へ限定する。"""

        tracker = ChannelRevisionTracker({"timeline": "blender:peer-001"})
        self.assertEqual(tracker.authority_for("timeline"), "blender:peer-001")
        for mapping in (
            {" ": "blender:peer-001"},
            {"timeline": "\t"},
            {"\ud800": "blender:peer-001"},
            {"timeline": "\ud800"},
        ):
            with self.subTest(mapping=repr(mapping)):
                with self.assertRaises(ValidationError):
                    ChannelRevisionTracker(mapping)

    def test_transfer_updates_authority_revision_and_content_sender_validation(self) -> None:
        """Authority移譲後は新Authorityのcontentだけを受理する。"""

        tracker = ChannelRevisionTracker({"timeline": "blender:peer-001"})
        self.assertEqual(tracker.authority_revision_for("timeline"), 0)
        self.assertEqual(tracker.transfer_authority("timeline", "blender:peer-001", "maya:peer-001", 0), 1)
        self.assertEqual(tracker.authority_for("timeline"), "maya:peer-001")
        self.assertEqual(tracker.authority_revision_for("timeline"), 1)
        self.assertEqual(tracker.accept_content("timeline", "maya:peer-001", 1), 1)
        with self.assertRaises(AuthorityViolation):
            tracker.accept_content("timeline", "blender:peer-001", 2)

    def test_transfer_rejects_unauthorized_or_stale_authority_without_mutation(self) -> None:
        """不正なAuthorityと古いauthority revisionはstateを変更しない。"""

        tracker = ChannelRevisionTracker({"timeline": "blender:peer-001"})
        with self.assertRaises(AuthorityViolation):
            tracker.transfer_authority("timeline", "maya:peer-001", "unity:peer-001", 0)
        with self.assertRaises(StaleRevision):
            tracker.transfer_authority("timeline", "blender:peer-001", "maya:peer-001", 1)
        self.assertEqual(tracker.authority_for("timeline"), "blender:peer-001")
        self.assertEqual(tracker.authority_revision_for("timeline"), 0)

    def test_unknown_and_invalid_channel_ids_fail_closed(self) -> None:
        """未知、空白、surrogateのChannel IDを拒否する。"""

        tracker = ChannelRevisionTracker({"timeline": "blender:peer-001"})
        for channel_id in ("missing", " ", "\ud800", None, 1):
            with self.subTest(channel_id=repr(channel_id)):
                with self.assertRaises(ValidationError):
                    tracker.authority_for(channel_id)  # type: ignore[arg-type]
                with self.assertRaises(ValidationError):
                    tracker.revision_for(channel_id)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
