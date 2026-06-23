"""Market clocks — one loop body, two time sources.

``ReplayClock`` iterates a fixed, ordered list of timestamps (deterministic). ``LiveClock`` yields
wall-clock ticks at a cadence while the IST cash market is open (09:15–15:30, Mon–Fri). Both let
the same ``RealtimeEngine.run_tick`` drive realtime and replay identically — the key reuse decision.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)


def is_market_open(now_ist: datetime) -> bool:
    # Holiday-aware: weekends + exchange holidays (data/nse_holidays.csv) via the trading calendar.
    from .trading_calendar import is_trading_day

    if not is_trading_day(now_ist.date()):
        return False
    return MARKET_OPEN <= now_ist.timetz().replace(tzinfo=None) <= MARKET_CLOSE


class ReplayClock:
    """Deterministic: yields a fixed sequence of ISO timestamps."""

    def __init__(self, start_ts: str, steps: int, cadence_s: int):
        self.start = datetime.fromisoformat(start_ts.replace("Z", "+00:00"))
        if self.start.tzinfo is None:
            self.start = self.start.replace(tzinfo=timezone.utc)
        self.steps = int(steps)
        self.cadence_s = int(cadence_s)

    def ticks(self):
        for i in range(self.steps):
            yield (self.start + timedelta(seconds=i * self.cadence_s)).isoformat()


class LiveClock:
    """Wall-clock ticks at a cadence; only while the IST market is open."""

    def __init__(self, cadence_s: int = 60):
        self.cadence_s = int(cadence_s)

    def now_ist(self) -> datetime:
        return datetime.now(IST)

    def tick(self) -> str | None:
        now = self.now_ist()
        return now.isoformat() if is_market_open(now) else None
