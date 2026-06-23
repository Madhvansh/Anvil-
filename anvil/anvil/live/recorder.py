"""Tick recorder — persist each live tick's analytics + per-strike chain to the DuckDB store.

This is what makes a LIVE session reproducible: recording every tick lets a post-close replay drive
the exact same loop over the exact same data, so ``live-paper == replay`` (the alignment
requirement). Reuses the existing ``SnapshotStore`` (idempotent writes) and ``pipeline.to_snapshot``
— no new storage. Wire it into a realtime run to capture the day for later replay.
"""

from __future__ import annotations

from ..pipeline import analyze_chain, to_snapshot
from ..store import SnapshotStore


class TickRecorder:
    def __init__(self, store: SnapshotStore | None = None):
        self.store = store or SnapshotStore()
        self.count = 0

    def record(self, payload: dict, chain, source: str) -> str:
        """Persist a computed analytics payload + its chain. Returns the snapshot id."""
        sid = self.store.write(to_snapshot(payload), payload, source=source, chain=chain)
        self.count += 1
        return sid

    def record_chain(self, chain, source: str) -> str:
        """Convenience: analyze a chain then record it (used when only the chain is on hand)."""
        return self.record(analyze_chain(chain, None, source=source), chain, source)

    def close(self) -> None:
        self.store.close()
