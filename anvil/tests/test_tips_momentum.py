"""End-to-end tests for the momentum prediction surface (tips.momentum.momentum_for_chain)."""

from __future__ import annotations

from anvil.ingest import get_connector
from anvil.tips.momentum import momentum_for_chain


def _chain(underlying="NIFTY"):
    return get_connector("demo").get_chain(underlying)


def test_momentum_surface_uptrend_series_fires():
    chain = _chain()
    closes = [100.0 + i * 0.6 for i in range(80)]          # clean uptrend across timeframes
    block = {"closes": closes, "bars_by_tf": {"1d": closes, "1h": closes, "15m": closes}}
    out = momentum_for_chain(chain, source="tip_live", equity=1_000_000.0, series=block)

    assert out["underlying"] == "NIFTY"
    assert out["has_series"] is True
    assert out["momentum"] is not None
    assert out["momentum"]["direction"] == "bullish"
    assert "mtf_trend" in {f["name"] for f in out["momentum_factors"]}
    assert set(out["timeframes"]) >= {"1d", "1h", "15m"}
    assert out["prediction"]["underlying"] == "NIFTY"      # full prediction always present
    # Public surface: prediction carries no sized/actionable owner payload.
    assert out["prediction"].get("actionable_tip") in (None, {})


def test_momentum_surface_no_series_abstains():
    out = momentum_for_chain(_chain(), source="tip_live", equity=1_000_000.0, series={})
    assert out["has_series"] is False
    assert out["momentum"] is None                          # no series → momentum abstains
    assert out["momentum_factors"] == [] or all(
        not f["fired"] for f in out["momentum_factors"])
    assert out["prediction"]["underlying"] == "NIFTY"       # spine still returns a prediction
