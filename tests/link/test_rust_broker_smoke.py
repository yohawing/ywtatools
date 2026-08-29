"""Python Clientと既ビルドRust Brokerのloopback smoke。"""

from __future__ import annotations

import os
import queue
import subprocess
import threading
import unittest
from pathlib import Path

from ywta_link.client import LinkClient
from ywta_link.frame import FrameError

_ROOT = Path(__file__).resolve().parents[2]
_BROKER_NAME = "ywta-link.exe" if os.name == "nt" else "ywta-link"
_BROKER_BINARY = _ROOT / "target" / "debug" / _BROKER_NAME


@unittest.skipUnless(
    _BROKER_BINARY.is_file(),
    "Rust Broker binary is absent; run cargo build -p ywta-link before this smoke test.",
)
class RustBrokerSmokeTest(unittest.TestCase):
    """既ビルドBrokerとのframe相互運用を検証する。"""

    def test_two_python_clients_receive_raw_binary_through_rust_broker(self) -> None:
        """hello、join、publish後にraw bodyがそのまま届く。"""

        process = self._start_broker()
        try:
            endpoint = self._read_endpoint(process)
            with (
                LinkClient(endpoint, "blender:peer-001") as sender,
                LinkClient(
                    endpoint,
                    "maya:peer-001",
                ) as receiver,
            ):
                sender.join("shot-010")
                receiver.join("shot-010")
                expected_body = bytes([0, 1, 2, 255])
                delivered = None
                for _ in range(10):
                    sender.publish("shot-010", raw_body=expected_body)
                    try:
                        candidate = receiver.receive(timeout=0.2)
                    except FrameError:
                        continue
                    if candidate.body == expected_body:
                        delivered = candidate
                        break

                self.assertIsNotNone(delivered, "Broker did not route publish within 2 seconds")
                assert delivered is not None
                self.assertEqual(delivered.envelope.sender, "blender:peer-001")
                self.assertEqual(delivered.body, expected_body)

            process.wait(timeout=3)
            self.assertEqual(process.returncode, 0)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()

    def _start_broker(self) -> subprocess.Popen[str]:
        """表示consoleなしで既ビルドBrokerを起動する。"""

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        return subprocess.Popen(
            [
                str(_BROKER_BINARY),
                "serve",
                "--bind",
                "127.0.0.1:0",
                "--idle-timeout",
                "1",
            ],
            cwd=_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=creationflags,
        )

    def _read_endpoint(self, process: subprocess.Popen[str]) -> str:
        """起動済みBrokerが出力するendpointを時間上限付きで読む。"""

        assert process.stdout is not None
        lines: queue.Queue[str] = queue.Queue()
        threading.Thread(target=lambda: lines.put(process.stdout.readline()), daemon=True).start()
        try:
            line = lines.get(timeout=3)
        except queue.Empty as exc:
            raise AssertionError("Broker did not report its endpoint within 3 seconds") from exc
        prefix = "YWTA_LINK_ENDPOINT="
        if not line.startswith(prefix):
            raise AssertionError(f"unexpected Broker startup output: {line!r}")
        return line.removeprefix(prefix).strip()


if __name__ == "__main__":
    unittest.main()
