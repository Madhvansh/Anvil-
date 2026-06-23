"""Scheduled-event factor — abstain from / fade into known macro events (RBI, Budget).

Around a scheduled event, implied premium is rich and direction is dominated by the event outcome,
so the honest move is to fade premium (SHORT_VOL) and flag abstention for directional/long-vol bets.
Reads the committed event calendar (``ingest.events``) off the chain's date — no new pricing. STRONG
as a GATE (per the plan), but India-context: treat as research-grade until the tip backtest proves it.
"""

from __future__ import annotations

from ..ingest.events import days_to_next_event
from ..strategy.types import SHORT_VOL
from .base import STRONG, FactorSignal, register

_WINDOW_DAYS = 3  # fire inside this many days of a scheduled event


@register("scheduled_event")
def scheduled_event(ctx) -> FactorSignal:
    nxt = days_to_next_event(getattr(ctx, "timestamp", "") or "")
    if not nxt or nxt["days"] > _WINDOW_DAYS:
        return FactorSignal("scheduled_event", False, 0.0, "", STRONG,
                            {"next_event": nxt})
    days = nxt["days"]
    strength = round(max(0.0, 1.0 - days / float(_WINDOW_DAYS + 1)), 3)
    return FactorSignal(
        "scheduled_event", True, strength, SHORT_VOL, STRONG,
        {"event": nxt["name"], "event_date": nxt["date"], "days_to_event": days,
         "abstain_directional": True, "india_unvalidated": True},
    )
