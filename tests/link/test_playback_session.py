"""Playback Sessionの最小構成と所有権を検証する。"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from ywta_link import (
    PlaybackHostEvent,
    PlaybackHostEventKind,
    PlaybackHostRange,
    PlaybackHostSnapshot,
    PlaybackSessionConfig,
    PlaybackSessionError,
    RationalRate,
    compose_playback_session,
)


class _Client:
    def __init__(self) -> None:
        self.joined: list[str] = []
        self.closed = 0
        self.fail_close = False

    def join(self, room: str) -> str:
        self.joined.append(room)
        return "join"

    def close(self) -> None:
        self.closed += 1
        if self.fail_close:
            raise RuntimeError("client cleanup")

    def receive(self, timeout: object = None) -> object:
        raise RuntimeError("not started")

    def publish(self, *args: object, **kwargs: object) -> str:
        return "publish"

    def subscribe(self, *args: object) -> str:
        return "subscribe"

    def unsubscribe(self, *args: object) -> str:
        return "unsubscribe"


class _Host:
    def __init__(self, on_change: object) -> None:
        self.on_change = on_change
        self.applied: list[PlaybackHostSnapshot] = []

    def apply(self, snapshot: PlaybackHostSnapshot) -> None:
        self.applied.append(snapshot)


class _Lifecycle:
    def __init__(self, host: _Host, runtime: object) -> None:
        self.host = host
        self.runtime = runtime
        self.started = 0
        self.closed = 0
        self.fail_close = False
        self.start_error: BaseException | None = None
        self.start_result = True
        self.close_result = True
        self.rollback_closed = False

    @property
    def status(self) -> SimpleNamespace:
        return SimpleNamespace(closed=self.rollback_closed)

    def start(self) -> bool:
        self.started += 1
        if self.start_error is not None:
            raise self.start_error
        return self.start_result

    def close(self) -> bool:
        self.closed += 1
        if self.fail_close:
            raise RuntimeError("cleanup")
        if self.close_result:
            self.rollback_closed = True
        return self.close_result


def _config(**values: object) -> PlaybackSessionConfig:
    data: dict[str, object] = {
        "peer_id": "maya:peer-001",
        "session_id": "session-001",
        "room": "room-001",
        "topic": "playback",
        "channel_id": "playback-main",
        "initial_authority": "maya:peer-001",
        "ticks_per_host_unit": 2,
        "host_unit_rate": RationalRate(24, 1),
        "time_unit": "frames",
    }
    data.update(values)
    return PlaybackSessionConfig(**data)  # type: ignore[arg-type]


class PlaybackSessionTest(unittest.TestCase):
    def _compose(self) -> tuple[object, _Client, _Host, _Lifecycle]:
        client = _Client()
        captured: dict[str, object] = {}

        def make_host(on_change: object) -> _Host:
            host = _Host(on_change)
            captured["host"] = host
            return host

        def make_lifecycle(host: _Host, runtime: object) -> _Lifecycle:
            lifecycle = _Lifecycle(host, runtime)
            captured["lifecycle"] = lifecycle
            return lifecycle

        session = compose_playback_session(_config(), make_host, make_lifecycle, lambda config: client)
        return session, client, captured["host"], captured["lifecycle"]  # type: ignore[return-value]

    def test_config_requires_explicit_valid_values(self) -> None:
        with self.assertRaises(PlaybackSessionError):
            _config(room=" ")
        with self.assertRaises(PlaybackSessionError):
            _config(ticks_per_host_unit=0)
        with self.assertRaises(TypeError):
            PlaybackSessionConfig("peer", "session", "room", "topic", "channel", "owner", 1, RationalRate(24, 1))

    def test_composition_binds_host_after_controller_and_uses_current_authority(self) -> None:
        session, client, host, lifecycle = self._compose()
        self.assertEqual(client.joined, ["room-001"])
        self.assertIs(lifecycle.host, host)
        self.assertTrue(callable(host.on_change))
        controller = lifecycle.runtime._controller
        self.assertEqual(controller._authority_provider("playback-main"), "maya:peer-001")
        self.assertTrue(session.start())

    def test_host_callback_before_bind_fails_and_closes_client(self) -> None:
        client = _Client()
        event = PlaybackHostEvent(
            PlaybackHostEventKind.PAUSED_SEEK,
            PlaybackHostSnapshot("paused", 0, PlaybackHostRange(0, 1), 1.0, "forward", "once", "frames", "change"),
        )

        def make_host(on_change: object) -> _Host:
            on_change(event)  # type: ignore[operator]
            return _Host(on_change)

        with self.assertRaisesRegex(PlaybackSessionError, "before PlaybackController binding"):
            compose_playback_session(_config(), make_host, lambda host, runtime: _Lifecycle(host, runtime), lambda config: client)
        self.assertGreaterEqual(client.closed, 1)

    def test_close_before_start_closes_runtime_client(self) -> None:
        session, client, _host, _lifecycle = self._compose()
        self.assertTrue(session.close())
        self.assertGreaterEqual(client.closed, 1)
        self.assertFalse(session.close())

    def test_started_close_delegates_lifecycle_before_client(self) -> None:
        session, client, _host, lifecycle = self._compose()
        session.start()
        self.assertTrue(session.close())
        self.assertEqual(lifecycle.closed, 1)
        self.assertGreaterEqual(client.closed, 1)

    def test_lifecycle_close_failure_keeps_client_for_retry(self) -> None:
        session, client, _host, lifecycle = self._compose()
        session.start()
        lifecycle.fail_close = True
        with self.assertRaises(PlaybackSessionError):
            session.close()
        self.assertEqual(client.closed, 0)
        lifecycle.fail_close = False
        self.assertTrue(session.close())

    def test_client_close_failure_retries_without_reclosing_lifecycle(self) -> None:
        session, client, _host, lifecycle = self._compose()
        session.start()
        client.fail_close = True
        with self.assertRaises(PlaybackSessionError):
            session.close()
        self.assertEqual(lifecycle.closed, 1)
        client.fail_close = False
        self.assertTrue(session.close())
        self.assertEqual(lifecycle.closed, 1)

    def test_failed_start_close_retries_lifecycle_cleanup(self) -> None:
        session, client, _host, lifecycle = self._compose()
        lifecycle.start_error = RuntimeError("start")
        with self.assertRaisesRegex(RuntimeError, "start"):
            session.start()
        self.assertTrue(session.close())
        self.assertEqual(lifecycle.closed, 1)
        self.assertGreaterEqual(client.closed, 1)

    def test_rolled_back_start_allows_closed_lifecycle_false_close(self) -> None:
        session, client, _host, lifecycle = self._compose()
        lifecycle.start_result = False
        lifecycle.close_result = False
        lifecycle.rollback_closed = True
        with self.assertRaises(PlaybackSessionError):
            session.start()
        self.assertTrue(session.close())
        self.assertEqual(lifecycle.closed, 1)
        self.assertGreaterEqual(client.closed, 1)

    def test_lifecycle_factory_failure_rolls_back_client(self) -> None:
        client = _Client()
        with self.assertRaisesRegex(RuntimeError, "lifecycle"):
            compose_playback_session(
                _config(),
                _Host,
                lambda host, runtime: (_ for _ in ()).throw(RuntimeError("lifecycle")),
                lambda config: client,
            )
        self.assertGreaterEqual(client.closed, 1)
        session = compose_playback_session(
            _config(),
            _Host,
            lambda host, runtime: _Lifecycle(host, runtime),
            lambda config: client,
        )
        session.close()

    def test_construction_rollback_failure_is_observable(self) -> None:
        client = _Client()
        client.fail_close = True

        def make_host(on_change: object) -> _Host:
            raise RuntimeError("host construction")

        with self.assertRaisesRegex(PlaybackSessionError, "construction rollback failed") as raised:
            compose_playback_session(
                _config(),
                make_host,
                lambda host, runtime: _Lifecycle(host, runtime),
                lambda config: client,
            )
        self.assertIsInstance(raised.exception.__cause__, RuntimeError)
        self.assertIn("host construction", str(raised.exception.__cause__))
        self.assertIn("client cleanup", str(raised.exception))
