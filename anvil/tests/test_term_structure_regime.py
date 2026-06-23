"""IV term-structure + regime: term-structure exposes a front/next slope + shape; crush_window
abstains on an imminent event/backwardation; regime is reported as an AGREEMENT COUNT with the
firing signals and NEVER an 'accuracy' figure (C9)."""

from __future__ import annotations

import numpy as np

from anvil.engine.implied_dist import implied_distribution
from anvil.engine.regime_score import RANGE, SQUEEZE, TREND, regime_score
from anvil.engine.term_structure import crush_window, expected_move_from_straddle, iv_term_structure
from anvil.ingest.base import attach_parity_forward
from anvil.ingest.demo import build_demo_chain


def test_regime_is_agreement_not_accuracy():
    closes = list(100.0 * np.exp(np.cumsum(np.full(60, 0.004))))  # steady uptrend
    r = regime_score(closes, gex_total=-5.0e6, backwardation=True)
    assert r["label"] in (TREND, RANGE, SQUEEZE, "neutral")
    assert set(("label", "agree_count", "signals_total", "signals")) <= set(r)
    assert r["agree_count"] <= r["signals_total"]
    assert "accuracy" not in str(r).lower()  # C9: no accuracy anywhere


def test_regime_runs_on_flat_series():
    closes = list(100.0 + np.sin(np.arange(60) * 0.3))
    r = regime_score(closes, gex_total=5.0e6, backwardation=False)
    assert r["signals_total"] >= 2 and "accuracy" not in str(r).lower()


def test_crush_window_abstains_on_event_or_backwardation():
    w = crush_window(days_to_event=1, event_name="RBI MPC", backwardation=True, crush_score=70)
    assert w["abstain"] and "RBI" in w["reason"]
    w2 = crush_window(days_to_event=20, event_name=None, backwardation=False, crush_score=10)
    assert not w2["abstain"]


def test_term_structure_shape_and_expected_move():
    front = attach_parity_forward(build_demo_chain("NIFTY", spot=24000.0, expiry="2026-07-31",
                                                   timestamp="2026-06-20T15:30:00+05:30"))
    nxt = attach_parity_forward(build_demo_chain("NIFTY", spot=24000.0, expiry="2026-08-28",
                                                 timestamp="2026-06-20T15:30:00+05:30"))
    ts = iv_term_structure([front, nxt])
    assert ts["n_expiries"] == 2 and ts["shape"] in ("contango", "backwardation", "flat")
    assert ts["front_iv"] and ts["next_iv"]
    em = expected_move_from_straddle(implied_distribution(front))
    assert em is None or em > 0
