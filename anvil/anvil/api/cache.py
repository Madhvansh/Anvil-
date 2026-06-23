"""In-process TTL cache for analytics payloads.

The slow part of any analytics request is fetching the option chain from the live
broker; the engine math itself is fast. A short TTL (default 45s) collapses a burst
of device reads of the same (source, underlying, expiry) into one upstream fetch.
Single-process and thread-safe (FastAPI runs sync endpoints in a threadpool). The
``Cache`` protocol keeps Redis a config-flip away once multi-tenant load justifies it.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Protocol


class Cache(Protocol):
    def get(self, key: str) -> Any | None: ...
    def set(self, key: str, value: Any) -> None: ...
    def clear(self) -> None: ...


class TTLCache:
    def __init__(self, ttl_s: float = 45.0) -> None:
        self.ttl_s = ttl_s
        self._data: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            expires_at, value = item
            if time.monotonic() >= expires_at:
                self._data.pop(key, None)
                return None
            return value

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = (time.monotonic() + self.ttl_s, value)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


ANALYZE_TTL_S = float(os.environ.get("ANVIL_ANALYZE_TTL", "45"))
ANALYZE_CACHE: TTLCache = TTLCache(ANALYZE_TTL_S)
