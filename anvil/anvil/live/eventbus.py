"""In-process event bus — one normalized stream for the realtime loop, recorder, and UI.

Broker feeds (Upstox WebSocket V3, Groww Feed, Kite WebSocket — wired when keys are present)
publish normalized events here; the realtime loop, the tick recorder, and the SSE/WS UI stream
subscribe. Dependency-free pub/sub over ``asyncio.Queue`` with drop-on-slow-consumer so one stuck
subscriber can't stall producers. The broker-specific WS clients attach as producers on top of this.
"""

from __future__ import annotations

import asyncio

# Normalized event types.
INDEX_TICK = "index_tick"
OPTION_TICK = "option_tick"
GREEKS = "greeks"
DEPTH = "depth"
OI_CHANGE = "oi_change"
PORTFOLIO = "portfolio"
MARKET_STATUS = "market_status"
PAPER_PNL = "paper_pnl"  # the loop publishes equity/P&L updates for the Simulator UI
PREDICTION = "prediction"  # the loop publishes the live per-underlying prediction + any issued tips
TIP_RESOLVED = "tip_resolved"  # a live tip reached its horizon and was settled (Phase 5)
TRUST_DIAL = "trust_dial"  # a compact reliability/coverage/accuracy-at-coverage snapshot (Phase 5)
COCKPIT_STATUS = "cockpit_status"  # supervisor heartbeat: mode/last-run/market-open (Wave 0)


class EventBus:
    def __init__(self, maxsize: int = 1000):
        self.maxsize = maxsize
        self._subs: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=self.maxsize)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)

    def publish(self, kind: str, data: dict) -> int:
        """Fan out an event to every subscriber. Drops on a full queue (slow consumer). Returns
        the number of subscribers that received it."""
        event = {"type": kind, **data}
        delivered = 0
        for q in list(self._subs):
            try:
                q.put_nowait(event)
                delivered += 1
            except asyncio.QueueFull:
                pass
        return delivered


_BUS: EventBus | None = None


def get_bus() -> EventBus:
    global _BUS
    if _BUS is None:
        _BUS = EventBus()
    return _BUS
