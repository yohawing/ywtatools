"""Playback Common v1をLink ClientのRoom/Topicへ接続するtransport。"""

from __future__ import annotations

from ._snapshot_sync import SnapshotTopicTransport
from .playback import PLAYBACK_SCHEMA, Playback, PlaybackValidationError
from .playback_controller import PlaybackController


class PlaybackTransportError(RuntimeError):
    """Playback transportの設定、lifecycle、wire検証、Client失敗を表す。"""


class PlaybackTransportThreadError(PlaybackTransportError):
    """owner thread以外からPlayback transportを操作したことを表す。"""


class PlaybackTopicTransport(SnapshotTopicTransport):
    """一つのRoom/TopicへPlayback publishと受信を束ねるtransport。"""

    schema = PLAYBACK_SCHEMA
    snapshot_type = Playback
    validation_error = PlaybackValidationError
    controller_type = PlaybackController
    error_type = PlaybackTransportError
    thread_error_type = PlaybackTransportThreadError
    label = "Playback"


__all__ = ("PlaybackTopicTransport", "PlaybackTransportError", "PlaybackTransportThreadError")
