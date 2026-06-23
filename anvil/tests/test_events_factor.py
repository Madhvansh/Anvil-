"""Scheduled-event calendar + factor: fires (SHORT_VOL, abstain) inside the event window, stays quiet
far from any event, and is registered so ``compute_factors`` picks it up."""

from __future__ import annotations

from anvil.factors import FACTORS
from anvil.factors.events import scheduled_event
from anvil.ingest.events import days_to_next_event


class _Ctx:
    def __init__(self, ts: str):
        self.timestamp = ts


def test_calendar_next_event():
    nxt = days_to_next_event("2026-01-30")
    assert nxt and nxt["name"] == "Union Budget" and nxt["days"] == 2


def test_fires_near_event():
    s = scheduled_event(_Ctx("2026-01-30T15:30:00+05:30"))
    assert s.fired and s.direction == "short_vol"
    assert s.drivers["abstain_directional"] and s.drivers["event"] == "Union Budget"


def test_quiet_far_from_event():
    assert not scheduled_event(_Ctx("2026-03-01T15:30:00+05:30")).fired


def test_registered():
    assert "scheduled_event" in FACTORS
