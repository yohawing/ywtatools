"""Common CameraのAuthority付き同期componentを検証する。"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from ywta_link import (
    AuthorityHandoffAccepted,
    AuthorityHandoffTracker,
    Camera,
    CameraController,
    CameraEchoGuard,
    CameraHandoffCoordinator,
    CameraSessionConfig,
    CameraSyncError,
    CameraSyncRuntime,
    CameraTopicTransport,
    CameraValidationError,
    Envelope,
    Frame,
    compose_camera_session,
)
from ywta_link.adapter import AdapterDispatch
from ywta_link.authority_transport import AuthorityHandoffTransport
from ywta_link.errors import AuthorityViolation

_FIXTURE = Path(__file__).resolve().parents[2] / "protocol" / "ywta-link" / "v1" / "valid" / "camera-v1.json"


def _camera(change_id: str = "camera-change-001") -> Camera:
    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    payload["change_id"] = change_id
    return Camera.from_dict(payload)


class _Client:
    def __init__(self, peer_id: str = "maya:peer-001") -> None:
        self.peer_id = peer_id
        self.calls: list[tuple[str, object]] = []
        self.closed = 0

    def join(self, room: str) -> str:
        self.calls.append(("join", room))
        return "join"

    def close(self) -> None:
        self.closed += 1

    def receive(self, timeout: object = None) -> Frame:
        raise RuntimeError("not started")

    def subscribe(self, room: str, topic: str) -> str:
        self.calls.append(("subscribe", (room, topic)))
        return "subscribe"

    def unsubscribe(self, room: str, topic: str) -> str:
        self.calls.append(("unsubscribe", (room, topic)))
        return "unsubscribe"

    def publish(self, room: str, **kwargs: object) -> str:
        self.calls.append(("publish", (room, kwargs)))
        return "publish-001"

    def request(self, room: str, target: str, **kwargs: object) -> str:
        self.calls.append(("request", (room, target, kwargs)))
        return kwargs["message_id"]  # type: ignore[return-value]

    def response(self, *args: object, **kwargs: object) -> str:
        return "response"


class _Host:
    def __init__(self, callback: object) -> None:
        self.callback = callback
        self.applied: list[Camera] = []

    def snapshot(self) -> Camera:
        return _camera("initial")

    def apply(self, camera: Camera) -> None:
        self.applied.append(camera)


class _Lifecycle:
    def __init__(self, host: _Host, runtime: object) -> None:
        self.host = host
        self.runtime = runtime
        self.started = 0
        self.closed = 0

    def start(self) -> bool:
        self.started += 1
        return True

    def close(self) -> bool:
        self.closed += 1
        self.runtime.close()
        return True


class CameraSyncTest(unittest.TestCase):
    def _runtime(self) -> tuple[CameraSyncRuntime, _Client]:
        client = _Client("local")
        tracker = AuthorityHandoffTracker({"camera-main": "local"}, "session")
        authority = AuthorityHandoffTransport(client, "room", tracker)
        transport = CameraTopicTransport(client, "room", "camera")
        controller = CameraController(
            "local", "camera-main", lambda channel: tracker.state_for(channel).authority, transport.publish, lambda value: None
        )
        coordinator = CameraHandoffCoordinator(
            "local", "camera-main", tracker, authority, controller, _camera("initial"), lambda value: None, 1.0
        )
        return CameraSyncRuntime(AdapterDispatch(client), authority, transport, controller, coordinator), client

    def test_camera_requires_change_id_and_positive_aspect_ratio(self) -> None:
        payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
        for field, value in (("change_id", " "), ("aspect_ratio", 0.0), ("aspect_ratio", -1.0)):
            payload[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(CameraValidationError):
                Camera.from_dict(payload)
            payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))

    def test_transport_publishes_and_applies_only_bound_camera_frames(self) -> None:
        client = _Client()
        transport = CameraTopicTransport(client, "room", "camera")
        applied: list[Camera] = []
        controller = CameraController(
            client.peer_id,
            "camera-main",
            lambda channel: "remote",
            transport.publish,
            applied.append,
        )
        transport.subscribe()
        camera = _camera("remote-change")
        frame = Frame(
            Envelope(
                1,
                "message",
                "publish",
                "remote",
                "room",
                None,
                "camera",
                None,
                "ywta.common.camera.v1",
                camera.to_dict(),
            )
        )
        self.assertTrue(transport.handle_frame(frame, controller))
        self.assertEqual(applied, [camera])
        transport.close()

    def test_controller_enforces_authority_and_suppresses_remote_echo(self) -> None:
        published: list[Camera] = []
        applied: list[Camera] = []
        authority = ["local"]
        controller = CameraController(
            "local",
            "camera-main",
            lambda channel: authority[0],
            published.append,
            applied.append,
        )
        local = _camera("local-change")
        self.assertTrue(controller.handle_host_change(local))
        self.assertEqual(published, [local])
        authority[0] = "remote"
        remote = _camera("remote-change")
        self.assertTrue(controller.apply_remote("remote", remote))
        self.assertFalse(controller.handle_host_change(remote, "remote"))
        self.assertEqual(applied, [remote])

    def test_controller_dependency_failures_latch_but_invalid_input_does_not(self) -> None:
        class _FailingGuard(CameraEchoGuard):
            def should_publish(self, origin: str, change_id: str) -> bool:
                raise RuntimeError("guard failed")

        failed = CameraController(
            "local", "camera", lambda channel: "local", lambda value: None, lambda value: None, _FailingGuard()
        )
        with self.assertRaisesRegex(RuntimeError, "guard failed"):
            failed.handle_host_change(_camera())
        self.assertTrue(failed.status.failed)

        provider_failed = CameraController(
            "local",
            "camera",
            lambda channel: (_ for _ in ()).throw(RuntimeError("provider failed")),
            lambda value: None,
            lambda value: None,
        )
        with self.assertRaisesRegex(RuntimeError, "provider failed"):
            provider_failed.handle_host_change(_camera())
        self.assertTrue(provider_failed.status.failed)

        class _RememberFailingGuard(CameraEchoGuard):
            def remember(self, origin: str, change_id: str) -> None:
                raise RuntimeError("remember failed")

        remember_failed = CameraController(
            "local", "camera", lambda channel: "remote", lambda value: None, lambda value: None, _RememberFailingGuard()
        )
        with self.assertRaisesRegex(RuntimeError, "remember failed"):
            remember_failed.apply_remote("remote", _camera())
        self.assertTrue(remember_failed.status.failed)

        healthy = CameraController("local", "camera", lambda channel: "authority", lambda value: None, lambda value: None)
        with self.assertRaises(CameraSyncError):
            healthy.handle_host_change({})  # type: ignore[arg-type]
        with self.assertRaises(CameraSyncError):
            healthy.apply_remote(" ", _camera())
        with self.assertRaises(AuthorityViolation):
            healthy.apply_remote("other", _camera())
        self.assertFalse(healthy.status.failed)
        healthy.close()

    def test_handoff_timeout_dependency_failures_are_latched_and_typed(self) -> None:
        runtime, _client = self._runtime()
        coordinator = runtime.coordinator
        coordinator._deadline = 0.0  # type: ignore[attr-defined]
        coordinator._clock = lambda: (_ for _ in ()).throw(RuntimeError("clock failed"))  # type: ignore[attr-defined]
        with self.assertRaisesRegex(CameraSyncError, "poll_timeout failed"):
            coordinator.poll_timeout()
        self.assertTrue(coordinator.status.failed)
        runtime.close()

        second, _client = self._runtime()
        coordinator = second.coordinator
        coordinator._deadline = 0.0  # type: ignore[attr-defined]
        coordinator._clock = lambda: 1.0  # type: ignore[attr-defined]
        coordinator._rollback_apply = lambda value: (_ for _ in ()).throw(RuntimeError("rollback failed"))  # type: ignore[attr-defined]
        with self.assertRaisesRegex(CameraSyncError, "rollback failed"):
            coordinator.poll_timeout()
        self.assertTrue(coordinator.status.failed)
        second.close()

    def test_runtime_requires_exact_start_and_promotes_timeout_in_same_pump(self) -> None:
        runtime, _client = self._runtime()
        runtime.authority_transport.subscribe = lambda: False  # type: ignore[method-assign]
        with self.assertRaisesRegex(CameraSyncError, "must return True"):
            runtime.start()
        self.assertTrue(runtime.status.failed)

        runtime, _client = self._runtime()
        runtime.authority_transport.subscribe = lambda: True  # type: ignore[method-assign]
        runtime.transport.subscribe = lambda: True  # type: ignore[method-assign]
        runtime.dispatch.start = lambda: True  # type: ignore[method-assign]
        runtime.dispatch.drain = lambda handler, max_items=None: 0  # type: ignore[method-assign]
        runtime.coordinator._deadline = 0.0  # type: ignore[attr-defined]
        runtime.coordinator._clock = lambda: 1.0  # type: ignore[attr-defined]
        self.assertTrue(runtime.start())
        with self.assertRaises(CameraSyncError):
            runtime.pump()
        self.assertTrue(runtime.status.failed)
        runtime.close()

    def test_runtime_close_retries_dispatch_and_always_attempts_controller(self) -> None:
        runtime, _client = self._runtime()
        calls: list[str] = []
        runtime.coordinator.close = lambda: True  # type: ignore[method-assign]
        runtime.authority_transport.close = lambda: True  # type: ignore[method-assign]
        runtime.transport.close = lambda: True  # type: ignore[method-assign]
        results = iter((False, True))
        runtime.dispatch.close_session = lambda: next(results)  # type: ignore[method-assign]
        runtime.controller.close = lambda: calls.append("controller") or True  # type: ignore[method-assign]
        with self.assertRaisesRegex(CameraSyncError, "did not stop"):
            runtime.close()
        self.assertEqual(calls, ["controller"])
        self.assertTrue(runtime.close())
        self.assertEqual(calls, ["controller", "controller"])

    def test_handoff_requests_authority_before_publishing_retained_camera(self) -> None:
        client = _Client("local")
        tracker = AuthorityHandoffTracker({"camera-main": "remote"}, "session")
        authority_transport = AuthorityHandoffTransport(client, "room", tracker)
        transport = CameraTopicTransport(client, "room", "camera")
        controller = CameraController(
            "local",
            "camera-main",
            lambda channel: tracker.state_for(channel).authority,
            transport.publish,
            lambda camera: None,
        )
        coordinator = CameraHandoffCoordinator(
            "local",
            "camera-main",
            tracker,
            authority_transport,
            controller,
            _camera("initial"),
            lambda camera: None,
            1.0,
        )
        authority_transport.subscribe()
        transport.subscribe()
        self.assertFalse(coordinator.handle_host_change(_camera("pending")))
        self.assertTrue(coordinator.status.pending)
        self.assertTrue(any(name == "request" for name, _ in client.calls))
        coordinator.close()
        authority_transport.close()
        transport.close()

    def test_accepted_handoff_reapplies_and_publishes_latest_camera(self) -> None:
        client = _Client("local")
        tracker = AuthorityHandoffTracker({"camera-main": "remote"}, "session")
        authority_transport = AuthorityHandoffTransport(client, "room", tracker)
        transport = CameraTopicTransport(client, "room", "camera")
        restored: list[Camera] = []
        controller = CameraController(
            "local",
            "camera-main",
            lambda channel: tracker.state_for(channel).authority,
            transport.publish,
            lambda camera: None,
        )
        coordinator = CameraHandoffCoordinator(
            "local",
            "camera-main",
            tracker,
            authority_transport,
            controller,
            _camera("initial"),
            restored.append,
            1.0,
        )
        authority_transport.subscribe()
        transport.subscribe()
        retained = _camera("pending")
        coordinator.handle_host_change(retained)
        pending = tracker.pending_for("camera-main")
        accepted = AuthorityHandoffAccepted(
            "session",
            "camera-main",
            "remote",
            "local",
            0,
            1,
            "pending",
        )
        frame = Frame(
            Envelope(
                1,
                "accepted-message",
                "publish",
                "remote",
                "room",
                None,
                "sync/session/control",
                pending.request_message_id,  # type: ignore[union-attr]
                "ywta.sync.authority.accepted.v1",
                accepted.to_dict(),
            )
        )
        self.assertTrue(coordinator.handle_authority_frame(frame))
        self.assertEqual(restored, [retained])
        camera_publishes = [call for call in client.calls if call[0] == "publish"]
        self.assertEqual(len(camera_publishes), 1)
        self.assertFalse(coordinator.status.pending)
        coordinator.close()
        authority_transport.close()
        transport.close()

    def test_session_composes_camera_direct_callback_and_owned_client(self) -> None:
        client = _Client()
        captured: dict[str, object] = {}

        def make_host(callback: object) -> _Host:
            host = _Host(callback)
            captured["host"] = host
            return host

        def make_lifecycle(host: _Host, runtime: object) -> _Lifecycle:
            lifecycle = _Lifecycle(host, runtime)
            captured["lifecycle"] = lifecycle
            return lifecycle

        config = CameraSessionConfig(
            "maya:peer-001",
            "session",
            "room",
            "camera",
            "camera-main",
            "maya:peer-001",
        )
        session = compose_camera_session(config, make_host, make_lifecycle, lambda value: client)
        host = captured["host"]
        lifecycle = captured["lifecycle"]
        self.assertTrue(callable(host.callback))  # type: ignore[attr-defined]
        self.assertTrue(session.start())
        self.assertTrue(session.close())
        self.assertEqual(lifecycle.closed, 1)  # type: ignore[attr-defined]
        self.assertGreaterEqual(client.closed, 1)

    def test_topic_lease_prevents_duplicate_transport_until_close(self) -> None:
        client = _Client()
        first = CameraTopicTransport(client, "room", "camera")
        with self.assertRaisesRegex(CameraSyncError, "already owned"):
            CameraTopicTransport(client, "room", "camera")
        first.close()
        replacement = CameraTopicTransport(client, "room", "camera")
        replacement.close()


if __name__ == "__main__":
    unittest.main()
