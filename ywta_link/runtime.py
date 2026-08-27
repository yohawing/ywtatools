"""YWTA Link Brokerのruntime manifestと実行file探索。"""

from __future__ import annotations

import ipaddress
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


# 起動直後にPopenが破棄され、まだ稼働中のBrokerが警告されるのを防ぐ。
_SPAWNED_BROKERS: list[subprocess.Popen[bytes]] = []


class RuntimeError(ValueError):
    """runtime manifest、実行file、またはbootstrapの検証失敗。"""


@dataclass(frozen=True)
class RuntimeManifest:
    """Rust Brokerが短命に公開するloopback endpoint。"""

    protocol_version: int
    endpoint: str
    pid: int
    token: str

    def validate(self) -> "RuntimeManifest":
        """v1のnumeric loopback endpointだけを受け入れる。"""

        if isinstance(self.protocol_version, bool) or not isinstance(self.protocol_version, int) or self.protocol_version != 1:
            raise RuntimeError("runtime protocol_version must be 1")
        if isinstance(self.pid, bool) or not isinstance(self.pid, int) or self.pid <= 0:
            raise RuntimeError("runtime pid must be a positive integer")
        if not isinstance(self.token, str) or not self.token:
            raise RuntimeError("runtime token must be a non-empty string")
        parse_loopback_endpoint(self.endpoint)
        return self


def read_runtime_manifest(path: str | os.PathLike[str]) -> RuntimeManifest:
    """completeなJSON manifestを読み、未知/不正な構造を拒否する。"""

    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"could not read runtime manifest: {exc}") from exc
    if not isinstance(value, dict) or set(value) != {"protocol_version", "endpoint", "pid", "token"}:
        raise RuntimeError("runtime manifest has an invalid field set")
    manifest = RuntimeManifest(**value)
    return manifest.validate()


def parse_loopback_endpoint(value: str) -> tuple[str, int]:
    """DNSを使わないnumeric loopback endpointを検証する。"""

    if not isinstance(value, str):
        raise RuntimeError("endpoint must be a string")
    if value.startswith("["):
        host, separator, port_text = value[1:].partition("]:")
        if not separator:
            raise RuntimeError("endpoint must use [ipv6]:port")
    else:
        host, separator, port_text = value.rpartition(":")
        if not separator or ":" in host:
            raise RuntimeError("endpoint must use numeric host:port")
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise RuntimeError("endpoint must be numeric host:port") from exc
    if not port_text.isdecimal():
        raise RuntimeError("endpoint port must be decimal")
    port = int(port_text)
    if not address.is_loopback or not 1 <= port <= 65535:
        raise RuntimeError("endpoint must be loopback with a valid port")
    return host, port


def default_install_root() -> Path:
    """User installのLink rootを返す。"""

    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("LOCALAPPDATA is required to resolve the user install")
    return Path(local_app_data) / "YWTA" / "Link"


def default_runtime_file() -> Path:
    """User install内の短命runtime manifest pathを返す。"""

    return default_install_root() / "runtime" / "v1" / "broker.json"


def resolve_broker_executable(
    explicit: str | os.PathLike[str] | None = None,
    *,
    install_root: str | os.PathLike[str] | None = None,
    environment: Mapping[str, str] | None = None,
) -> Path:
    """明示指定、環境変数、User installの順でBrokerを解決する。"""

    if explicit is not None:
        return _require_executable(Path(explicit))
    environment = os.environ if environment is None else environment
    environment_path = environment.get("YWTA_LINK_EXE")
    if environment_path:
        return _require_executable(Path(environment_path))
    root = Path(install_root) if install_root is not None else default_install_root()
    return _resolve_user_install(root)


def spawn_broker(
    executable: str | os.PathLike[str],
    runtime_file: str | os.PathLike[str],
    *,
    idle_timeout: int,
) -> subprocess.Popen[bytes]:
    """stdout/stderrを塞がない候補Broker processを起動する。"""

    runtime_path = Path(runtime_file)
    if not runtime_path.is_absolute():
        raise RuntimeError("runtime file path must be absolute")
    if isinstance(idle_timeout, bool) or not isinstance(idle_timeout, int) or idle_timeout < 0:
        raise RuntimeError("idle_timeout must be a non-negative integer")
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        _reap_spawned_brokers()
        process = subprocess.Popen(
            [
                str(_require_executable(Path(executable))),
                "serve",
                "--bind",
                "127.0.0.1:0",
                "--idle-timeout",
                str(idle_timeout),
                "--runtime-file",
                str(runtime_path),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        _SPAWNED_BROKERS.append(process)
        return process
    except OSError as exc:
        raise RuntimeError(f"could not start Broker: {exc}") from exc


def retire_stale_runtime(
    runtime_file: str | os.PathLike[str],
    expected_token: str | None = None,
    *,
    stale_after: float,
) -> bool:
    """古い同一manifestだけをrename後に再検証して削除する。"""

    runtime_path = Path(runtime_file)
    if isinstance(stale_after, bool) or not isinstance(stale_after, (int, float)) or stale_after < 0:
        raise RuntimeError("stale_after must be non-negative")
    if expected_token is not None and (not isinstance(expected_token, str) or not expected_token):
        raise RuntimeError("expected_token must be a non-empty string")
    try:
        original = runtime_path.read_bytes()
        modified_at = runtime_path.stat().st_mtime
    except OSError:
        return False
    if time.time() - modified_at < stale_after:
        return False
    try:
        manifest = _read_runtime_manifest_bytes(original)
    except RuntimeError:
        manifest = None
    if expected_token is not None and (manifest is None or manifest.token != expected_token):
        return False
    if manifest is not None and _process_is_alive(manifest.pid):
        return False
    stale_path = runtime_path.with_name(f"{runtime_path.name}.stale-{os.getpid()}-{time.time_ns()}")
    try:
        os.replace(runtime_path, stale_path)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise RuntimeError(f"could not retire stale runtime manifest: {exc}") from exc
    try:
        moved = stale_path.read_bytes()
    except OSError:
        return False
    if moved != original:
        _restore_runtime_if_unclaimed(stale_path, runtime_path)
        return False
    try:
        moved_manifest = _read_runtime_manifest_bytes(moved)
    except RuntimeError:
        moved_manifest = None
    if expected_token is not None and (moved_manifest is None or moved_manifest.token != expected_token):
        _restore_runtime_if_unclaimed(stale_path, runtime_path)
        return False
    try:
        stale_path.unlink()
    except FileNotFoundError:
        pass
    return True


def _resolve_user_install(install_root: Path) -> Path:
    """current.jsonの相対executableをinstall root内だけで解決する。"""

    current_path = install_root / "current.json"
    try:
        current = json.loads(current_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"could not read current.json: {exc}") from exc
    if not isinstance(current, dict) or set(current) != {"executable", "protocol_version", "version"}:
        raise RuntimeError("current.json has an invalid field set")
    executable = current.get("executable")
    if not isinstance(executable, str) or not executable:
        raise RuntimeError("current.json executable must be a non-empty string")
    if (
        isinstance(current["protocol_version"], bool)
        or not isinstance(current["protocol_version"], int)
        or current["protocol_version"] != 1
    ):
        raise RuntimeError("current.json protocol_version must be 1")
    if not isinstance(current["version"], str) or not current["version"]:
        raise RuntimeError("current.json version must be a non-empty string")
    relative_path = Path(executable)
    if relative_path.is_absolute():
        raise RuntimeError("current.json executable must be relative")
    root = install_root.resolve()
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise RuntimeError("current.json executable escapes install root") from exc
    return _require_executable(candidate)


def _require_executable(path: Path) -> Path:
    """存在する通常fileだけをBroker executableとして返す。"""

    if not path.is_file():
        raise RuntimeError(f"Broker executable does not exist: {path}")
    return path


def _reap_spawned_brokers() -> None:
    """終了済みBrokerのPopen参照だけを解放する。"""

    _SPAWNED_BROKERS[:] = [process for process in _SPAWNED_BROKERS if process.poll() is None]


def _read_runtime_manifest_bytes(value: bytes) -> RuntimeManifest:
    """移動済みの同一bytesを再検証してmanifestへ変換する。"""

    try:
        decoded = json.loads(value.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"could not decode runtime manifest: {exc}") from exc
    if not isinstance(decoded, dict) or set(decoded) != {"protocol_version", "endpoint", "pid", "token"}:
        raise RuntimeError("runtime manifest has an invalid field set")
    return RuntimeManifest(**decoded).validate()


def _restore_runtime_if_unclaimed(stale_path: Path, runtime_path: Path) -> None:
    """rename中に内容が変わった場合だけ、空のcanonical pathへ戻す。"""

    if runtime_path.exists():
        return
    try:
        os.replace(stale_path, runtime_path)
    except OSError:
        pass


def _process_is_alive(pid: int) -> bool:
    """PID再利用を安全側に倒し、判定不能なprocessも生存中として扱う。"""

    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            # Access deniedとPID再利用の区別が付かない場合はmanifestを残す。
            return ctypes.get_last_error() not in {87, 1168}
        try:
            exit_code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return True
            return exit_code.value == still_active
        finally:
            kernel32.CloseHandle(handle)

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    return True
