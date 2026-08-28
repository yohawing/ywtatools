"""DCC非依存Playback Controllerの同期境界を検証する。"""

from __future__ import annotations

import threading
import unittest

from ywta_link import (
    Playback,
    PlaybackController,
    PlaybackControllerError,
    PlaybackControllerThreadError,
    PlaybackEchoGuard,
    PlaybackHostEvent,
    PlaybackHostEventKind,
    PlaybackHostRange,
    PlaybackHostSnapshot,
    PlaybackTimeMapper,
    RationalRate,
)
from ywta_link.errors import AuthorityViolation


def _mapper() -> PlaybackTimeMapper:
    """テスト用のframesからwire tickへのmapperを返す。"""

    return PlaybackTimeMapper(
        ticks_per_host_unit=4,
        host_unit_rate=RationalRate(24, 1),
        time_unit="frames",
    )


def _snapshot(change_id: str = "change-001", **overrides: object) -> PlaybackHostSnapshot:
    """テスト用のHost snapshotを作る。"""

    values: dict[str, object] = {
        "state": "playing",
        "position": 1.25,
        "playback_range": PlaybackHostRange(0.5, 3.25),
        "speed": 1.5,
        "direction": "forward",
        "loop_mode": "loop",
        "time_unit": "frames",
        "change_id": change_id,
        "approximated_fields": (),
    }
    values.update(overrides)
    return PlaybackHostSnapshot(**values)  # type: ignore[arg-type]


def _event(change_id: str = "change-001", **overrides: object) -> PlaybackHostEvent:
    """テスト用のHost eventを作る。"""

    kind = overrides.pop("kind", PlaybackHostEventKind.PAUSED_SEEK)
    return PlaybackHostEvent(kind, _snapshot(change_id, **overrides))  # type: ignore[arg-type]


class PlaybackControllerTest(unittest.TestCase):
    """Playback ControllerのAuthority、mapping、echo、lifecycleを検証する。"""

    def test_local_authority_event_is_mapped_and_published(self) -> None:
        """local AuthorityのeventだけをPlaybackへ変換してpublishする。"""

        published: list[Playback] = []
        channels: list[str] = []
        controller = PlaybackController(
            "blender:peer-001",
            "timeline",
            _mapper(),
            lambda channel: channels.append(channel) or "blender:peer-001",
            published.append,
            lambda snapshot: None,
        )

        self.assertTrue(controller.handle_host_event(_event()))
        self.assertEqual(channels, ["timeline"])
        self.assertEqual(len(published), 1)
        self.assertEqual(published[0].position.time, 5)
        self.assertEqual(published[0].playback_range.start, 2)

    def test_non_authority_event_is_not_published(self) -> None:
        """現在Authorityでないlocal eventは無視し、publisherを呼ばない。"""

        published: list[Playback] = []
        controller = PlaybackController(
            "maya:peer-001",
            "timeline",
            _mapper(),
            lambda channel: "blender:peer-001",
            published.append,
            lambda snapshot: None,
        )

        self.assertFalse(controller.handle_host_event(_event()))
        self.assertEqual(published, [])

    def test_remote_origin_echo_is_suppressed_and_new_local_event_is_allowed(self) -> None:
        """既定Guardでremote applyの即時callbackを抑止し、local eventはpublishする。"""

        published: list[Playback] = []
        echo_results: list[bool] = []
        controller: PlaybackController
        current_authority = ["blender:peer-001"]

        def host_apply(snapshot: PlaybackHostSnapshot) -> None:
            echo_results.append(
                controller.handle_host_event(
                    PlaybackHostEvent(PlaybackHostEventKind.PAUSED_SEEK, snapshot),
                    origin_peer_id="blender:peer-001",
                )
            )

        controller = PlaybackController(
            "maya:peer-001",
            "timeline",
            _mapper(),
            lambda channel: current_authority[0],
            published.append,
            host_apply,
        )
        remote = _mapper().to_playback(_snapshot())

        self.assertTrue(controller.apply_remote("blender:peer-001", remote))
        self.assertEqual(echo_results, [False])
        self.assertEqual(published, [])

        current_authority[0] = "maya:peer-001"
        self.assertTrue(controller.handle_host_event(_event("change-002")))
        self.assertEqual(len(published), 1)

    def test_remote_apply_requires_current_authority(self) -> None:
        """Authority以外のoriginはHostへ適用せずAuthorityViolationにする。"""

        applied: list[PlaybackHostSnapshot] = []
        controller = PlaybackController(
            "maya:peer-001",
            "timeline",
            _mapper(),
            lambda channel: "blender:peer-001",
            lambda playback: None,
            applied.append,
        )

        with self.assertRaises(AuthorityViolation):
            controller.apply_remote("unity:peer-001", _mapper().to_playback(_snapshot()))
        self.assertEqual(applied, [])
        self.assertFalse(controller.status.failed)

    def test_self_origin_is_ignored_without_host_apply(self) -> None:
        """handoff後でもlocal self-originをloopbackとして再適用しない。"""

        applied: list[PlaybackHostSnapshot] = []
        controller = PlaybackController(
            "blender:peer-001",
            "timeline",
            _mapper(),
            lambda channel: "maya:peer-001",
            lambda playback: None,
            applied.append,
        )

        self.assertFalse(controller.apply_remote("blender:peer-001", _mapper().to_playback(_snapshot())))
        self.assertEqual(applied, [])

    def test_apply_failure_enters_failed_and_future_operations_fail_closed(self) -> None:
        """Host apply失敗を記録し、以後の同期操作を停止する。"""

        def fail_apply(snapshot: PlaybackHostSnapshot) -> None:
            raise ValueError("host apply failed")

        controller = PlaybackController(
            "maya:peer-001",
            "timeline",
            _mapper(),
            lambda channel: "blender:peer-001",
            lambda playback: None,
            fail_apply,
            PlaybackEchoGuard(),
        )
        remote = _mapper().to_playback(_snapshot())

        with self.assertRaisesRegex(ValueError, "host apply failed"):
            controller.apply_remote("blender:peer-001", remote)
        self.assertTrue(controller.status.failed)
        self.assertFalse(controller.status.closed)
        self.assertIsNotNone(controller.status.error)
        self.assertEqual(controller.status.error.exception_type, "ValueError")  # type: ignore[union-attr]
        self.assertFalse(controller.handle_host_event(_event("change-002")))
        self.assertFalse(controller.apply_remote("blender:peer-001", remote))

    def test_publish_failure_enters_failed(self) -> None:
        """publisher失敗もFailedとして観測できる。"""

        def fail_publish(playback: Playback) -> None:
            raise RuntimeError("publish failed")

        controller = PlaybackController(
            "blender:peer-001",
            "timeline",
            _mapper(),
            lambda channel: "blender:peer-001",
            fail_publish,
            lambda snapshot: None,
        )

        with self.assertRaisesRegex(RuntimeError, "publish failed"):
            controller.handle_host_event(_event())
        self.assertTrue(controller.status.failed)
        self.assertFalse(controller.handle_host_event(_event("change-002")))

    def test_mapping_failure_enters_failed(self) -> None:
        """mappingできないHost値を黙ってpublishせずFailedにする。"""

        controller = PlaybackController(
            "blender:peer-001",
            "timeline",
            _mapper(),
            lambda channel: "blender:peer-001",
            lambda playback: None,
            lambda snapshot: None,
        )

        with self.assertRaises(Exception):
            controller.handle_host_event(_event(position=0.1))
        self.assertTrue(controller.status.failed)

    def test_close_is_idempotent_and_prevents_session_reuse(self) -> None:
        """closeは二度目を安全に無視し、closed後のControllerを再利用させない。"""

        controller = PlaybackController(
            "blender:peer-001",
            "timeline",
            _mapper(),
            lambda channel: "blender:peer-001",
            lambda playback: None,
            lambda snapshot: None,
            PlaybackEchoGuard(),
        )

        self.assertTrue(controller.close())
        self.assertFalse(controller.close())
        self.assertTrue(controller.status.closed)
        self.assertFalse(controller.status.failed)
        self.assertFalse(controller.handle_host_event(_event()))
        self.assertFalse(controller.apply_remote("blender:peer-001", _mapper().to_playback(_snapshot())))

    def test_injected_guard_cannot_be_reused_across_sessions(self) -> None:
        """注入Guardの同時利用とclose後の再利用を拒否する。"""

        guard = PlaybackEchoGuard()
        controller = PlaybackController(
            "blender:peer-001",
            "timeline",
            _mapper(),
            lambda channel: "blender:peer-001",
            lambda playback: None,
            lambda snapshot: None,
            guard,
        )
        for _closed in (False, True):
            if _closed:
                controller.close()
            with self.assertRaisesRegex(PlaybackControllerError, "already owned"):
                PlaybackController(
                    "maya:peer-001",
                    "timeline",
                    _mapper(),
                    lambda channel: "maya:peer-001",
                    lambda playback: None,
                    lambda snapshot: None,
                    guard,
                )

    def test_publisher_reentry_fails_closed(self) -> None:
        """publisherからの同期再入で重複publishしない。"""

        controller: PlaybackController

        def publish(_playback: Playback) -> None:
            controller.handle_host_event(_event("change-reentrant"))

        controller = PlaybackController(
            "blender:peer-001",
            "timeline",
            _mapper(),
            lambda channel: "blender:peer-001",
            publish,
            lambda snapshot: None,
        )
        with self.assertRaisesRegex(PlaybackControllerError, "during publish"):
            controller.handle_host_event(_event())
        self.assertTrue(controller.status.failed)

    def test_publisher_cannot_close_controller_reentrantly(self) -> None:
        """publish中のcloseで操作結果とlifecycleを矛盾させない。"""

        controller: PlaybackController

        def publish(_playback: Playback) -> None:
            controller.close()

        controller = PlaybackController(
            "blender:peer-001",
            "timeline",
            _mapper(),
            lambda channel: "blender:peer-001",
            publish,
            lambda snapshot: None,
        )
        with self.assertRaisesRegex(PlaybackControllerError, "close cannot run during publish"):
            controller.handle_host_event(_event())
        self.assertTrue(controller.status.failed)
        self.assertFalse(controller.status.closed)

    def test_host_apply_allows_matching_echo_but_rejects_nested_apply(self) -> None:
        """apply中は一致echoだけを抑止し、別のremote apply再入を拒否する。"""

        controller: PlaybackController
        remote = _mapper().to_playback(_snapshot())

        def apply(snapshot: PlaybackHostSnapshot) -> None:
            self.assertFalse(
                controller.handle_host_event(
                    PlaybackHostEvent(PlaybackHostEventKind.PAUSED_SEEK, snapshot),
                    origin_peer_id="blender:peer-001",
                )
            )
            controller.apply_remote("blender:peer-001", remote)

        controller = PlaybackController(
            "maya:peer-001",
            "timeline",
            _mapper(),
            lambda channel: "blender:peer-001",
            lambda playback: None,
            apply,
        )
        with self.assertRaisesRegex(PlaybackControllerError, "during apply"):
            controller.apply_remote("blender:peer-001", remote)
        self.assertTrue(controller.status.failed)

    def test_operations_are_owner_thread_only(self) -> None:
        """handle、apply、closeを生成元以外のthreadから呼べない。"""

        controller = PlaybackController(
            "blender:peer-001",
            "timeline",
            _mapper(),
            lambda channel: "blender:peer-001",
            lambda playback: None,
            lambda snapshot: None,
        )
        remote = _mapper().to_playback(_snapshot())
        errors: list[Exception] = []

        def call_from_worker() -> None:
            for operation in (
                lambda: controller.handle_host_event(_event()),
                lambda: controller.apply_remote("blender:peer-001", remote),
                controller.close,
            ):
                try:
                    operation()
                except Exception as exc:
                    errors.append(exc)

        worker = threading.Thread(target=call_from_worker)
        worker.start()
        worker.join()
        self.assertEqual([type(error) for error in errors], [PlaybackControllerThreadError] * 3)
        self.assertFalse(controller.status.closed)
        controller.close()

    def test_invalid_event_and_constructor_inputs_fail_closed(self) -> None:
        """eventとconstructorの型境界を厳密に検証する。"""

        with self.assertRaises(PlaybackControllerError):
            PlaybackController(
                "peer",
                "channel",
                object(),  # type: ignore[arg-type]
                lambda channel: "peer",
                lambda playback: None,
                lambda snapshot: None,
            )

        controller = PlaybackController(
            "peer",
            "channel",
            _mapper(),
            lambda channel: "peer",
            lambda playback: None,
            lambda snapshot: None,
        )
        with self.assertRaises(PlaybackControllerError):
            controller.handle_host_event({})  # type: ignore[arg-type]
        with self.assertRaises(PlaybackControllerError):
            controller.apply_remote("peer", {})  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
