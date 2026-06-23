"""The unified Decision Brief: every non-FAVORABLE verdict carries a `flip_condition` (C10); near a
scheduled event the verdict is ABSTAIN and the strike-action rows render muted; the brief is labeled
analytics, not edge-proven."""

from __future__ import annotations

import numpy as np

from anvil.engine.decision_brief import FAVORABLE, decision_brief
from anvil.ingest.base import attach_parity_forward
from anvil.ingest.demo import build_demo_chain
from anvil.strategy.context import SignalContext


def _ctx(ts="2026-06-20T15:30:00+05:30"):
    ch = attach_parity_forward(build_demo_chain("NIFTY", spot=24000.0, expiry="2026-07-31", timestamp=ts))
    return SignalContext(ch, source="demo")


def _hist(n=140, sigma=0.18, seed=0):
    rng = np.random.default_rng(seed)
    s = 24000.0
    rows = []
    for _ in range(n):
        o = s
        for _ in range(60):
            s *= np.exp(-0.5 * sigma**2 / 252 / 60 + sigma * np.sqrt(1 / 252 / 60) * rng.standard_normal())
        rows.append((o, max(o, s) * 1.001, min(o, s) * 0.999, s))
    return rows


def test_brief_verdict_flip_and_strikes():
    b = decision_brief(_ctx(), history_ohlc=_hist(), horizon_days=5, n_paths=4000).to_dict()
    assert b["verdict"] in (FAVORABLE, "NEUTRAL", "UNFAVORABLE", "ABSTAIN")
    if b["verdict"] != FAVORABLE:
        assert b["flip_condition"]  # C10
    assert b["strikes"] and all("p_touch_phys" in s for s in b["strikes"])
    assert "not edge-proven" in b["disclaimer"].lower()


def test_brief_abstains_near_event_and_mutes_strikes():
    b = decision_brief(_ctx("2026-01-30T15:30:00+05:30"), history_ohlc=_hist(), horizon_days=5,
                       n_paths=4000).to_dict()
    assert b["verdict"] == "ABSTAIN"
    assert b["flip_condition"] and "Budget" in b["environment"]["crush_window"]["reason"]
    assert b["strikes"] and all(s["muted"] for s in b["strikes"])
