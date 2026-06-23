"""Bhavcopy ingestion: parse a real-shaped F&O EOD CSV → OptionChain with a real-settle
forward, and confirm the implied distribution builds on it (the backtester's data path)."""

from datetime import date
from pathlib import Path

import pytest

from anvil.engine.implied_dist import implied_distribution
from anvil.ingest.bhavcopy import build_chains, parse_fo_bhavcopy

FIX = Path(__file__).parent / "fixtures" / "bhavcopy_fo_sample.csv"


def _rows():
    return parse_fo_bhavcopy(FIX.read_text())


def test_parse_keeps_index_and_filters_stocks():
    rows = _rows()
    assert {r.symbol for r in rows} == {"NIFTY"}        # RELIANCE filtered by index_only
    assert any(r.is_future for r in rows)
    assert sum(r.is_option for r in rows) >= 8


def test_keep_all_when_index_only_false():
    rows = parse_fo_bhavcopy(FIX.read_text(), index_only=False)
    assert any(r.symbol == "RELIANCE" for r in rows)


def test_build_chain_uses_real_settle_forward():
    chains = build_chains(_rows(), asof=date(2026, 6, 12), index_close={"NIFTY": 24010.0})
    assert len(chains) == 1
    ch = chains[0]
    assert ch.underlying == "NIFTY"
    assert ch.future_price == pytest.approx(24000.0)
    assert ch.future_price_source == "nse_bhavcopy_settle"   # the rail: real forward, tagged
    assert ch.spot == pytest.approx(24010.0)
    assert len(ch.strikes()) >= 4


def test_implied_distribution_builds_from_bhavcopy_chain():
    ch = build_chains(_rows(), asof=date(2026, 6, 12), index_close={"NIFTY": 24010.0})[0]
    dist = implied_distribution(ch)
    assert dist is not None
    assert dist.forward == pytest.approx(24000.0, rel=1e-6)
    assert dist.forward_source == "nse_bhavcopy_settle"
    # IV recovered from settle prices ≈ the 12% the fixture was priced at
    assert dist.atm_iv == pytest.approx(0.12, abs=0.02)


def test_expired_chain_is_skipped_point_in_time():
    # asof AFTER expiry → no chain built (you cannot forecast an already-settled expiry)
    assert build_chains(_rows(), asof=date(2026, 7, 1)) == []


def test_spot_falls_back_to_future_when_no_index_close():
    ch = build_chains(_rows(), asof=date(2026, 6, 12))[0]  # no index_close supplied
    assert ch.spot == pytest.approx(24000.0)               # falls back to futures settle
