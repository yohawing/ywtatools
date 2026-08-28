"""Playback Common v1をLink ClientのRoom/Topicへ接続するtransport。"""

from __future__ import annotations

import threading
import weakref
from collections.abc import Mapping
from typing import Any

from .client import LinkClient
from .frame import Frame
from .playback import PLAYBACK_SCHEMA, Playback, PlaybackValidationError
from .playback_controller import PlaybackController


_LEASES: weakref.WeakKeyDictionary[object, dict[tuple[str, str], weakref.ReferenceType[object]]] = weakref.WeakKeyDictionary()
_LEASES_LOCK = threading.Lock()


class PlaybackTransportError(RuntimeError):
    """Playback transportの設定、lifecycle、wire検証、Client失敗を表す。"""


class PlaybackTransportThreadError(PlaybackTransportError):
    """owner thread以外からPlayback transportを操作したことを表す。"""


class PlaybackTopicTransport:
    """一つのRoom/TopicへPlayback publishと受信を束ねるDCC非依存transport。"""

    def __init__(self, client: LinkClient, room: str, topic: str) -> None:
        """Clientの既存接続を借用し、owner threadを記録する。"""

        for method_name in ("publish", "subscribe", "unsubscribe"):
            if not callable(getattr(client, method_name, None)):
                raise PlaybackTransportError(f"client must provide callable {method_name}()")
        self._client = client
        self._room = _identifier(room, "room")
        self._topic = _identifier(topic, "topic")
        self._owner_thread_id = threading.get_ident()
        self._active = False
        self._closed = False
        _claim_lease(client, self._room, self._topic, self)

    @property
    def room(self) -> str:
        """購読対象のRoom IDを返す。"""

        return self._room

    @property
    def topic(self) -> str:
        """購読対象のTopic IDを返す。"""

        return self._topic

    @property
    def active(self) -> bool:
        """subscribe成功後で、closeされていないかを返す。"""

        return self._active

    @property
    def closed(self) -> bool:
        """close成功済みかを返す。"""

        return self._closed

    def subscribe(self) -> bool:
        """Room/Topicを一度だけ購読し、成功後にactiveへ遷移する。"""

        self._require_owner()
        self._require_open()
        if self._active:
            return False
        self._call_client("subscribe", self._client.subscribe, self._room, self._topic)
        self._active = True
        return True

    def publish(self, playback: Playback) -> str:
        """Playbackをbound Topicへpublishし、transport message IDを返す。"""

        self._require_owner()
        self._require_open()
        self._require_active()
        if type(playback) is not Playback:
            raise PlaybackTransportError("playback must be exactly a Playback")
        result = self._call_client(
            "publish",
            self._client.publish,
            self._room,
            topic=self._topic,
            schema=PLAYBACK_SCHEMA,
            body=playback.to_dict(),
        )
        if not isinstance(result, str) or not result:
            raise PlaybackTransportError("client.publish() must return a non-empty string message ID")
        return result

    def handle_frame(self, frame: Frame, controller: PlaybackController) -> bool:
        """bound TopicのPlayback frameだけをControllerへ渡す。"""

        self._require_owner()
        self._require_open()
        self._require_active()
        if type(frame) is not Frame:
            raise PlaybackTransportError("frame must be exactly a Frame")
        if type(controller) is not PlaybackController:
            raise PlaybackTransportError("controller must be exactly a PlaybackController")
        envelope = frame.envelope
        if envelope.type != "publish" or envelope.room != self._room or envelope.topic != self._topic:
            return False
        if envelope.schema != PLAYBACK_SCHEMA:
            raise PlaybackTransportError("Playback frame schema must be ywta.common.playback.v1")
        if frame.body:
            raise PlaybackTransportError("Playback frame must not contain a raw binary body")
        if not isinstance(envelope.body, Mapping):
            raise PlaybackTransportError("Playback frame body must be a JSON object")
        try:
            playback = Playback.from_dict(envelope.body)
        except PlaybackValidationError as exc:
            raise PlaybackTransportError(f"invalid Playback frame body: {exc}") from exc
        try:
            result = controller.apply_remote(envelope.sender, playback)
        except Exception as exc:
            raise PlaybackTransportError(f"controller.apply_remote() failed: {_error_text(exc)}") from exc
        if not isinstance(result, bool):
            raise PlaybackTransportError("controller.apply_remote() must return bool")
        return result

    def close(self) -> bool:
        """購読を解除して閉じる。解除失敗時はretry可能なactive stateを保持する。"""

        self._require_owner()
        if self._closed:
            return False
        if self._active:
            self._call_client("unsubscribe", self._client.unsubscribe, self._room, self._topic)
            self._active = False
        self._closed = True
        _release_lease(self._client, self._room, self._topic, self)
        return True

    def _require_owner(self) -> None:
        """生成元thread以外からの操作を拒否する。"""

        if threading.get_ident() != self._owner_thread_id:
            raise PlaybackTransportThreadError("PlaybackTopicTransport operation must run on its owner thread")

    def _require_open(self) -> None:
        """close後の操作を拒否する。"""

        if self._closed:
            raise PlaybackTransportError("PlaybackTopicTransport is closed")

    def _require_active(self) -> None:
        """購読成功前の操作を拒否する。"""

        if not self._active:
            raise PlaybackTransportError("PlaybackTopicTransport is not subscribed")

    @staticmethod
    def _call_client(operation: str, method: Any, *args: Any, **kwargs: Any) -> Any:
        """Client例外をtransport境界で型付けして再送出する。"""

        try:
            return method(*args, **kwargs)
        except PlaybackTransportError:
            raise
        except Exception as exc:
            raise PlaybackTransportError(f"client.{operation}() failed: {_error_text(exc)}") from exc


def _identifier(value: object, field_name: str) -> str:
    """空白だけでないUTF-8のRoom/Topic IDを受け入れる。"""

    if not isinstance(value, str) or not value or not value.strip():
        raise PlaybackTransportError(f"{field_name} must be a non-whitespace string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise PlaybackTransportError(f"{field_name} must be valid UTF-8") from exc
    return value


def _claim_lease(client: object, room: str, topic: str, owner: object) -> None:
    """同じClient内のRoom/Topicを一つのTransportへ排他的に貸し出す。"""

    key = (room, topic)
    try:
        with _LEASES_LOCK:
            leases = _LEASES.setdefault(client, {})
            existing = leases.get(key)
            if existing is not None and existing() is not None:
                raise PlaybackTransportError("Room/Topic is already owned by another Playback transport")
            leases[key] = weakref.ref(owner)
    except TypeError as exc:
        raise PlaybackTransportError("client must support identity-based weak references") from exc


def _release_lease(client: object, room: str, topic: str, owner: object) -> None:
    """close成功後に自身が所有するRoom/Topic leaseだけを解放する。"""

    key = (room, topic)
    with _LEASES_LOCK:
        leases = _LEASES.get(client)
        if leases is None:
            return
        existing = leases.get(key)
        if existing is not None and existing() is owner:
            del leases[key]
        if not leases:
            del _LEASES[client]


def _error_text(error: Exception) -> str:
    """ClientまたはController例外を安全な短い文字列へ変換する。"""

    try:
        message = str(error)
    except Exception:
        message = "<unprintable exception>"
    return message[:1024]


__all__ = ("PlaybackTopicTransport", "PlaybackTransportError", "PlaybackTransportThreadError")
