"""In-process registry of background LIVE runs.

A live run executes on the SERVER as an asyncio task, independent of any client — it keeps running
when the user switches tabs, navigates away, or closes the browser, until market close or an explicit
stop. Single-worker: like the EventBus/RealtimeEngine module singletons, this registry is per-process,
so live mode requires uvicorn ``--workers 1`` (the compose stack runs a single worker).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field


@dataclass
class LiveRunHandle:
    run_id: int
    stop_event: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None


class LiveRunRegistry:
    def __init__(self) -> None:
        self._handles: dict[int, LiveRunHandle] = {}

    def create(self, run_id: int) -> LiveRunHandle:
        h = LiveRunHandle(run_id=run_id)
        self._handles[run_id] = h
        return h

    def get(self, run_id: int) -> LiveRunHandle | None:
        return self._handles.get(run_id)

    def stop(self, run_id: int) -> bool:
        h = self._handles.get(run_id)
        if h is not None:
            h.stop_event.set()
            return True
        return False

    def discard(self, run_id: int) -> None:
        self._handles.pop(run_id, None)

    def active(self) -> list[int]:
        return [rid for rid, h in self._handles.items() if h.task is not None and not h.task.done()]


_REGISTRY = LiveRunRegistry()


def get_registry() -> LiveRunRegistry:
    return _REGISTRY
