"""Camera automatic Session bootstrapのcontract test。"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from ywta_link import (
    AuthorityHandoffAccepted,
    Camera,
    CameraBootstrapConfig,
    CameraBootstrapError,
    Envelope,
    Frame,
    bootstrap_camera_session,
)
from ywta_link.authority import AUTHORITY_ACCEPTED_SCHEMA, AUTHORITY_SNAPSHOT_SCHEMA

_FIXTURE = Path(__file__).resolve().parents[2] / "protocol" / "ywta-link" / "v1" / "valid" / "camera-v1.json"


def _camera() -> Camera:
    return Camera.from_dict(json.loads(_FIXTURE.read_text(encoding="utf-8")))


def _frame(
    *,
    sender: str,
    target: str | None,
    correlation: str,
    schema: str,
    body: object,
    message_type: str = "response",
    topic: str | None = None,
) -> Frame:
    return Frame(Envelope(1, "message", message_type, sender, "default", target, topic, correlation, schema, body))


class _Client:
    def __init__(self, peer_id: str, frames: list[Frame]) -> None:
        self.peer_id = peer_id
        self.frames = frames
        self.calls: list[tuple[object, ...]] = []
        self.closed = 0

    def join(self, room: str) -> str:
        self.calls.append(("join", room))
        return "join"

    def request(self, room: str, target: str, **kwargs: object) -> str:
        schema = kwargs["schema"]
        result = "slot" if schema == "ywta.session.slot.join.v1" else "snapshot"
        self.calls.append(("request", room, target, schema))
        return result

    def subscribe(self, room: str, topic: str) -> str:
        self.calls.append(("subscribe", room, topic))
        return "subscribe"

    def unsubscribe(self, room: str, topic: str) -> str:
        return "unsubscribe"

    def receive(self, timeout: object = None) -> Frame:
        return self.frames.pop(0)

    def publish(self, *args: object, **kwargs: object) -> str:
        return "publish"

    def response(self, *args: object, **kwargs: object) -> str:
        return "response"

    def close(self) -> None:
        self.closed += 1


class _Host:
    def __init__(self, callback: object) -> None:
        self.callback = callback

    def snapshot(self) -> Camera:
        return _camera()

    def apply(self, camera: Camera) -> None:
        pass


class _Lifecycle:
    def __init__(self, host: _Host, runtime: object) -> None:
        self.runtime = runtime

    def start(self) -> bool:
        return True

    def close(self) -> bool:
        self.runtime.close()
        return True


def _config(**values: object) -> CameraBootstrapConfig:
    data = {
        "application_id": "maya",
        "application": "Maya",
        "application_version": "2024",
        "plugin_version": "1.0",
    }
    data.update(values)
    return CameraBootstrapConfig(**data)  # type: ignore[arg-type]


def _descriptor(config: CameraBootstrapConfig, peer: str, *, created: bool, state_peer: str | None = None) -> dict[str, object]:
    authority = peer if created else "blender:peer"
    return {
        "slot_id": config.slot_id,
        "session_id": "camera-session",
        "initial_authority": authority,
        "metadata": config.slot_metadata,
        "created": created,
        "state_peer": peer if created else state_peer or authority,
    }


class CameraBootstrapTest(unittest.TestCase):
    def test_defaults_metadata_and_presence_are_camera_specific(self) -> None:
        config = _config()
        self.assertEqual(
            (config.room, config.slot_id, config.channel_id, config.topic), ("default", "camera-default.v1", "camera", "camera")
        )
        self.assertEqual(config.slot_metadata["camera_schema"], "ywta.common.camera.v1")
        self.assertEqual(
            config.presence("maya:peer").capabilities,
            ("camera.apply.v1", "camera.read.v1", "sync.authority.v1"),
        )

    def test_fresh_slot_composes_camera_session(self) -> None:
        config = _config()
        clients: list[_Client] = []

        def connect(peer: str, presence: object) -> _Client:
            client = _Client(
                peer,
                [
                    _frame(
                        sender="ywta-link:broker",
                        target=peer,
                        correlation="slot",
                        schema="ywta.session.slot.descriptor.v1",
                        body=_descriptor(config, peer, created=True),
                    )
                ],
            )
            clients.append(client)
            return client

        session = bootstrap_camera_session(config, _Host, _Lifecycle, connect)
        self.assertEqual(session.authority_tracker.state_for("camera").authority, clients[0].peer_id)
        session.close()

    def test_existing_slot_reconciles_snapshot_and_buffered_accepted(self) -> None:
        config = _config()
        state_peer = "blender:peer"

        def connect(peer: str, presence: object) -> _Client:
            accepted = AuthorityHandoffAccepted("camera-session", "camera", state_peer, peer, 0, 1, "camera-change")
            return _Client(
                peer,
                [
                    _frame(
                        sender="ywta-link:broker",
                        target=peer,
                        correlation="slot",
                        schema="ywta.session.slot.descriptor.v1",
                        body=_descriptor(config, peer, created=False, state_peer=state_peer),
                    ),
                    _frame(
                        sender=state_peer,
                        target=None,
                        correlation="handoff",
                        schema=AUTHORITY_ACCEPTED_SCHEMA,
                        body=accepted.to_dict(),
                        message_type="publish",
                        topic="sync/camera-session/control",
                    ),
                    _frame(
                        sender=state_peer,
                        target=peer,
                        correlation="snapshot",
                        schema=AUTHORITY_SNAPSHOT_SCHEMA,
                        body={
                            "session_id": "camera-session",
                            "channel_id": "camera",
                            "authority": state_peer,
                            "authority_revision": 0,
                        },
                    ),
                ],
            )

        session = bootstrap_camera_session(config, _Host, _Lifecycle, connect)
        state = session.authority_tracker.state_for("camera")
        self.assertEqual((state.authority, state.revision), (session.authority_transport.client.peer_id, 1))
        session.close()

    def test_existing_slot_uses_authority_snapshot_without_handoff(self) -> None:
        config = _config()
        state_peer = "blender:peer"

        def connect(peer: str, presence: object) -> _Client:
            return _Client(
                peer,
                [
                    _frame(
                        sender="ywta-link:broker",
                        target=peer,
                        correlation="slot",
                        schema="ywta.session.slot.descriptor.v1",
                        body=_descriptor(config, peer, created=False, state_peer=state_peer),
                    ),
                    _frame(
                        sender=state_peer,
                        target=peer,
                        correlation="snapshot",
                        schema=AUTHORITY_SNAPSHOT_SCHEMA,
                        body={
                            "session_id": "camera-session",
                            "channel_id": "camera",
                            "authority": state_peer,
                            "authority_revision": 0,
                        },
                    ),
                ],
            )

        session = bootstrap_camera_session(config, _Host, _Lifecycle, connect)
        self.assertEqual(session.authority_tracker.state_for("camera").authority, state_peer)
        session.close()

    def test_invalid_descriptor_rolls_back_connected_client(self) -> None:
        config = _config(max_attempts=1)
        clients: list[_Client] = []

        def connect(peer: str, presence: object) -> _Client:
            descriptor = _descriptor(config, peer, created=True)
            descriptor["metadata"] = {**config.slot_metadata, "camera_schema": "wrong"}
            client = _Client(
                peer,
                [
                    _frame(
                        sender="ywta-link:broker",
                        target=peer,
                        correlation="slot",
                        schema="ywta.session.slot.descriptor.v1",
                        body=descriptor,
                    )
                ],
            )
            clients.append(client)
            return client

        with self.assertRaises(CameraBootstrapError):
            bootstrap_camera_session(config, _Host, _Lifecycle, connect)
        self.assertEqual(clients[0].closed, 1)


if __name__ == "__main__":
    unittest.main()
