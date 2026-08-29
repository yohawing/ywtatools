"""Maya Camera同期SessionのMain Thread lifecycle。"""

from __future__ import annotations

from typing import Any

from .lifecycle import (
    MayaPlaybackLifecycle,
    MayaPlaybackLifecycleError,
    MayaPlaybackLifecycleStatus,
    MayaPlaybackLifecycleUnavailableError,
)


MayaCameraLifecycleError = MayaPlaybackLifecycleError
MayaCameraLifecycleUnavailableError = MayaPlaybackLifecycleUnavailableError
MayaCameraLifecycleStatus = MayaPlaybackLifecycleStatus


class _CameraPump:
    """Camera Hostのdirty状態を送信してからRuntimeをpumpする。"""

    def __init__(self, runtime: Any, host: Any) -> None:
        if not callable(getattr(host, "flush", None)):
            raise MayaCameraLifecycleError("host.flush is unavailable")
        self._runtime = runtime
        self._host = host

    def start(self) -> bool:
        """Runtimeを開始する。"""

        return self._runtime.start()

    def pump(self, *, max_items: int | None = None) -> Any:
        """local Camera変更を送信してからremote更新を処理する。"""

        self._host.flush()
        return self._runtime.pump(max_items=max_items)

    def close(self) -> bool:
        """Runtimeを終了する。"""

        return self._runtime.close()


class MayaCameraLifecycle(MayaPlaybackLifecycle):
    """既存Maya lifecycleへCamera固有のflush順序だけを追加する。"""

    def __init__(self, runtime: Any, host: Any, **options: Any) -> None:
        """Camera runtimeと固定済みHostをMain Thread lifecycleへ接続する。"""

        super().__init__(_CameraPump(runtime, host), host, **options)


__all__ = (
    "MayaCameraLifecycle",
    "MayaCameraLifecycleError",
    "MayaCameraLifecycleStatus",
    "MayaCameraLifecycleUnavailableError",
)
