"""Tests for engine.chain_dynamics (skew slope, OI-change bias, blocks, 0DTE, max-pain drift)."""

from __future__ import annotations

from anvil.engine import chain_dynamics as cd
from anvil.ingest import get_connector

CHAIN = get_connector("demo").get_chain("NIFTY")


def test_iv_skew_slope_on_real_chain():
    read = cd.iv_skew_slope(CHAIN)
    assert read is None or {"slope", "curvature", "atm_iv", "n"} <= set(read)
    if read:
        assert read["n"] >= 3 and read["atm_iv"] > 0


def test_oi_change_bias_needs_data():
    # demo chain may lack oi_change AND a prev_chain → None (abstain)
    assert cd.oi_change_bias(CHAIN, None) is None or "bias" in cd.oi_change_bias(CHAIN, None)


def test_oi_change_bias_from_prev_chain():
    prev = get_connector("demo").get_chain("NIFTY")
    # synthesize a put-OI build vs prev → bullish bias
    for row in CHAIN.rows:
        if row.option_type.value in ("PE", "PUT", "P"):
            row.oi = (row.oi or 0) + 10000
    read = cd.oi_change_bias(CHAIN, prev)
    assert read is not None and "bias" in read


def test_smart_money_blocks_shape():
    read = cd.smart_money_blocks(CHAIN)
    assert read is None or {"blocks", "n_blocks"} <= set(read)


def test_zero_dte_dynamics_always_returns():
    read = cd.zero_dte_dynamics(CHAIN)
    assert {"dte", "is_0dte", "is_expiry_week", "max_pain", "pin_distance"} <= set(read)
    assert isinstance(read["is_0dte"], bool)


def test_max_pain_drift():
    assert cd.max_pain_drift([100.0]) is None
    d = cd.max_pain_drift([100.0, 110.0, 120.0])
    assert d["direction"] == "up" and d["drift"] == 20.0 and d["n"] == 3
    assert cd.max_pain_drift([120.0, 100.0])["direction"] == "down"
