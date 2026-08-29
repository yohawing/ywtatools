"""runtime manifest、Broker探索、bootstrapの検証。"""

from __future__ import annotations

import json
import os
import queue
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from ywta_link.client import LinkClient, LinkClientError
from ywta_link.frame import FrameError
from ywta_link.runtime import (
    RuntimeError,
    read_runtime_manifest,
    resolve_broker_executable,
    retire_stale_runtime,
)

_ROOT = Path(__file__).resolve().parents[2]
_BROKER_NAME = "ywta-link.exe" if os.name == "nt" else "ywta-link"
_BROKER_BINARY = _ROOT / "target" / "debug" / _BROKER_NAME


def _manifest(token: str = "owner-token") -> dict[str, object]:
    """有効なv1 runtime manifestを作る。"""

    return {
        "protocol_version": 1,
        "endpoint": "127.0.0.1:34567",
        "pid": 12345,
        "token": token,
    }


class RuntimeUnitTest(unittest.TestCase):
    """manifestとUser install探索を副作用を小さく検証する。"""

    def test_manifest_rejects_non_loopback_endpoint(self) -> None:
        """runtime manifestはloopback以外のendpointを拒否する。"""

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.json"
            value = _manifest()
            value["endpoint"] = "192.168.1.10:34567"
            path.write_text(json.dumps(value), encoding="utf-8")

            with self.assertRaises(RuntimeError):
                read_runtime_manifest(path)

    def test_bootstrap_rejects_invalid_timeouts_before_side_effects(self) -> None:
        """負値やboolのtimeoutをProcess起動前に拒否する。"""

        for arguments in (
            {"startup_timeout": 0},
            {"startup_timeout": float("nan")},
            {"stale_after": -1},
            {"stale_after": float("inf")},
            {"idle_timeout": 0},
            {"idle_timeout": True},
        ):
            with self.assertRaises(ValueError):
                LinkClient.connect_or_start("python:peer", **arguments)

    def test_executable_resolution_uses_explicit_then_environment_then_install(self) -> None:
        """PATHを使わず、定義済み優先順位だけで実行fileを選ぶ。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            explicit = root / "explicit.exe"
            environment_executable = root / "environment.exe"
            install_executable = root / "versions" / "v1" / "ywta-link.exe"
            for executable in (explicit, environment_executable, install_executable):
                executable.parent.mkdir(parents=True, exist_ok=True)
                executable.write_bytes(b"test")
            (root / "current.json").write_text(
                json.dumps(
                    {
                        "protocol_version": 1,
                        "version": "v1",
                        "executable": "versions/v1/ywta-link.exe",
                    }
                ),
                encoding="utf-8",
            )
            environment = {"YWTA_LINK_EXE": str(environment_executable)}

            self.assertEqual(
                resolve_broker_executable(explicit, install_root=root, environment=environment),
                explicit,
            )
            self.assertEqual(
                resolve_broker_executable(install_root=root, environment=environment),
                environment_executable,
            )
            self.assertEqual(resolve_broker_executable(install_root=root, environment={}), install_executable)

    def test_current_json_malformed_or_escaping_path_is_rejected(self) -> None:
        """current.jsonは壊れたJSONとinstall root外への相対pathを拒否する。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = root / "current.json"
            current.write_text("{", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                resolve_broker_executable(install_root=root, environment={})
            current.write_text(json.dumps({"executable": "../escape.exe"}), encoding="utf-8")
            with self.assertRaises(RuntimeError):
                resolve_broker_executable(install_root=root, environment={})

    def test_current_json_requires_protocol_and_nonempty_version(self) -> None:
        """User installのcurrent.jsonは互換性metadataを省略できない。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ywta-link.exe").write_bytes(b"test")
            for value in (
                {"executable": "ywta-link.exe", "version": "v1"},
                {"executable": "ywta-link.exe", "protocol_version": 1, "version": ""},
            ):
                (root / "current.json").write_text(json.dumps(value), encoding="utf-8")
                with self.assertRaises(RuntimeError):
                    resolve_broker_executable(install_root=root, environment={})

    def test_stale_runtime_is_renamed_then_removed(self) -> None:
        """同じ古いtokenだけをstale名へ原子的に退避して消す。"""

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.json"
            value = _manifest()
            value["pid"] = 2_147_483_647
            path.write_text(json.dumps(value), encoding="utf-8")
            os.utime(path, (time.time() - 10, time.time() - 10))

            self.assertTrue(retire_stale_runtime(path, "owner-token", stale_after=1))
            self.assertFalse(path.exists())
            self.assertFalse(list(Path(directory).glob("runtime.json.stale-*")))

    def test_stale_retirement_rejects_non_finite_age_without_removing_file(self) -> None:
        """NaNや無限値でfresh manifestを誤回収しない。"""

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.json"
            path.write_text("{", encoding="utf-8")
            for stale_after in (float("nan"), float("inf")):
                with self.assertRaises(RuntimeError):
                    retire_stale_runtime(path, stale_after=stale_after)
                self.assertTrue(path.exists())

    def test_fresh_runtime_is_not_retired_during_startup_race(self) -> None:
        """新しいmanifestは接続直後のraceでも削除しない。"""

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.json"
            value = _manifest()
            value["pid"] = 2_147_483_647
            path.write_text(json.dumps(value), encoding="utf-8")

            self.assertFalse(retire_stale_runtime(path, "owner-token", stale_after=1))
            self.assertTrue(path.exists())

    def test_fresh_partial_runtime_waits_until_startup_deadline(self) -> None:
        """起動途中のpartial JSONは恒久エラーではなくdeadlineまで待機する。"""

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.json"
            path.write_text("{", encoding="utf-8")
            started_at = time.monotonic()

            with self.assertRaisesRegex(LinkClientError, "did not become reachable"):
                LinkClient.connect_or_start(
                    "python:peer",
                    runtime_file=str(path),
                    startup_timeout=0.15,
                    stale_after=1,
                )

            self.assertGreaterEqual(time.monotonic() - started_at, 0.1)
            self.assertTrue(path.exists())

    def test_old_partial_runtime_is_revalidated_then_removed(self) -> None:
        """古いpartial JSONは移動後にも壊れていることを確認してから消す。"""

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.json"
            path.write_text("{", encoding="utf-8")
            os.utime(path, (time.time() - 10, time.time() - 10))

            self.assertTrue(retire_stale_runtime(path, stale_after=1))
            self.assertFalse(path.exists())
            self.assertFalse(list(Path(directory).glob("runtime.json.stale-*")))

    def test_live_owner_runtime_is_not_retired_after_handshake_failures(self) -> None:
        """live PIDのvalid manifestはhandshake失敗後も安全側へ残す。"""

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.json"
            value = _manifest()
            value["pid"] = os.getpid()
            path.write_text(json.dumps(value), encoding="utf-8")
            os.utime(path, (time.time() - 10, time.time() - 10))

            self.assertFalse(retire_stale_runtime(path, "owner-token", stale_after=1))
            self.assertTrue(path.exists())

    def test_stale_reclaim_keeps_successor_manifest(self) -> None:
        """rename直後に後継がclaimしても、そのmanifestを削除しない。"""

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.json"
            value = _manifest()
            value["pid"] = 2_147_483_647
            path.write_text(json.dumps(value), encoding="utf-8")
            os.utime(path, (time.time() - 10, time.time() - 10))
            successor = _manifest("successor-token")
            real_replace = os.replace

            def replace_and_claim(source: object, destination: object) -> None:
                real_replace(source, destination)
                path.write_text(json.dumps(successor), encoding="utf-8")

            with patch("ywta_link.runtime.os.replace", side_effect=replace_and_claim):
                self.assertTrue(retire_stale_runtime(path, "owner-token", stale_after=1))

            self.assertEqual(read_runtime_manifest(path).token, "successor-token")
            self.assertFalse(list(Path(directory).glob("runtime.json.stale-*")))

    def test_crashed_candidate_is_respawned_before_deadline(self) -> None:
        """claim失敗などで即終了した候補はdeadline内に再起動する。"""

        class DeadCandidate:
            """即時終了したPopenの最小代替。"""

            @staticmethod
            def poll() -> int:
                return 1

        with tempfile.TemporaryDirectory() as directory:
            runtime_path = Path(directory) / "runtime.json"
            with (
                patch("ywta_link.runtime.resolve_broker_executable", return_value=Path("broker.exe")),
                patch("ywta_link.runtime.spawn_broker", return_value=DeadCandidate()) as spawn,
                self.assertRaisesRegex(LinkClientError, "did not become reachable"),
            ):
                LinkClient.connect_or_start(
                    "python:peer",
                    runtime_file=str(runtime_path),
                    startup_timeout=0.25,
                )

            self.assertGreaterEqual(spawn.call_count, 2)


@unittest.skipUnless(
    _BROKER_BINARY.is_file(),
    "Rust Broker binary is absent; run cargo build -p ywta-link before this bootstrap smoke test.",
)
class RuntimeBootstrapSmokeTest(unittest.TestCase):
    """複数Python callerがRustの単一runtime leaseへ収束することを検証する。"""

    def test_concurrent_callers_connect_to_one_runtime_owner(self) -> None:
        """二重spawn候補のうち一つだけがmanifestを所有する。"""

        with tempfile.TemporaryDirectory() as directory:
            runtime_path = Path(directory) / "runtime" / "broker.json"
            barrier = threading.Barrier(2)
            results: queue.Queue[LinkClient | BaseException] = queue.Queue()
            workers = [
                threading.Thread(
                    target=self._connect_worker,
                    args=(barrier, results, f"python:peer-{index}", runtime_path),
                )
                for index in range(2)
            ]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=8)
                self.assertFalse(worker.is_alive(), "bootstrap worker did not finish")
            outcomes = [results.get_nowait() for _ in range(2)]
            failures = [outcome for outcome in outcomes if isinstance(outcome, BaseException)]
            self.assertFalse(failures, failures)
            clients = [outcome for outcome in outcomes if isinstance(outcome, LinkClient)]
            try:
                self.assertEqual(len(clients), 2)
                self.assertEqual(clients[0].endpoint, clients[1].endpoint)
                manifest = read_runtime_manifest(runtime_path)
                self.assertEqual(manifest.endpoint, f"{clients[0].endpoint[0]}:{clients[0].endpoint[1]}")
                cleanup_deadline = time.monotonic() + 1
                while any(runtime_path.parent.glob(f".{runtime_path.name}.*.tmp")) and time.monotonic() < cleanup_deadline:
                    time.sleep(0.01)
                self.assertEqual(list(runtime_path.parent.iterdir()), [runtime_path])
            finally:
                for client in clients:
                    client.close()
            deadline = time.monotonic() + 4
            while runtime_path.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertFalse(runtime_path.exists(), "Broker did not remove its runtime manifest")

    def test_runtime_client_reconnects_after_broker_shutdown(self) -> None:
        """runtime bootstrap設定を同一Clientで再利用し、Room広告を復元する。"""

        with tempfile.TemporaryDirectory() as directory:
            runtime_path = Path(directory) / "runtime" / "broker.json"
            client = LinkClient.connect_or_start(
                "python:reconnect",
                runtime_file=str(runtime_path.resolve()),
                executable=str(_BROKER_BINARY),
                idle_timeout=1,
                startup_timeout=6,
                stale_after=0.1,
            )
            receiver: LinkClient | None = None
            try:
                client.join("room-reconnect")
                client.subscribe("room-reconnect", "topic-reconnect")
                client.close()
                self._wait_for_runtime_removal(runtime_path)

                self.assertIs(client.reconnect(), client)
                receiver = LinkClient(client.endpoint, "python:receiver").connect(timeout=1)
                receiver.join("room-reconnect")
                delivered = None
                for _ in range(5):
                    client.publish("room-reconnect", raw_body=b"reconnected-bytes")
                    try:
                        delivered = receiver.receive(timeout=0.2)
                        break
                    except FrameError:
                        pass
                self.assertIsNotNone(delivered, "receiver did not observe reconnected room publish")

                assert delivered is not None
                self.assertEqual(delivered.envelope.sender, "python:reconnect")
                self.assertEqual(delivered.body, b"reconnected-bytes")
            finally:
                client.close()
                if receiver is not None:
                    receiver.close()
            self._wait_for_runtime_removal(runtime_path)

    def _wait_for_runtime_removal(self, runtime_path: Path) -> None:
        """idle Brokerがmanifestを削除するまで短く待機する。"""

        deadline = time.monotonic() + 4
        while runtime_path.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(runtime_path.exists(), "Broker did not remove its runtime manifest")

    @staticmethod
    def _connect_worker(
        barrier: threading.Barrier,
        results: queue.Queue[LinkClient | BaseException],
        peer_id: str,
        runtime_path: Path,
    ) -> None:
        """同時起動barrier後にbootstrap結果をqueueへ入れる。"""

        try:
            barrier.wait()
            results.put(
                LinkClient.connect_or_start(
                    peer_id,
                    runtime_file=str(runtime_path.resolve()),
                    executable=str(_BROKER_BINARY),
                    idle_timeout=1,
                    startup_timeout=6,
                    stale_after=0.1,
                )
            )
        except BaseException as exc:
            results.put(exc)


if __name__ == "__main__":
    unittest.main()
