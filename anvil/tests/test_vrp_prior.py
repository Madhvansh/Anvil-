"""Phase 5 — the VRP-harvest PRIOR (backtest/vrp_prior). Parameter-free, causal: sell the India-VIX-
priced 1-day ATM NIFTY straddle vs the real next-day move. Degrades gracefully without a cache."""

import anvil.backtest.vrp_prior as vp
from anvil.backtest.vrp_prior import run_vrp_prior


def test_insufficient_history(monkeypatch):
    monkeypatch.setattr(vp.yahoo, "read_cache", lambda sym: [])
    r = run_vrp_prior()
    assert r["error"] == "insufficient history"


def test_vrp_prior_computes_and_is_labeled(monkeypatch):
    dates = [f"2026-01-{d:02d}" for d in range(1, 36)]  # 35 days → 34 trading days (≥30)
    idx = [{"date": d, "c": 24000.0 * (1.0 + (0.001 if i % 2 else -0.001)), "o": 1, "h": 1, "l": 1,
            "volume": 1} for i, d in enumerate(dates)]
    vix = [{"date": d, "c": 13.0, "o": 1, "h": 1, "l": 1, "volume": 1} for d in dates]
    monkeypatch.setattr(vp.yahoo, "read_cache",
                        lambda sym: idx if sym == "^NSEI" else (vix if sym == "^INDIAVIX" else []))
    r = run_vrp_prior(capital=1_000_000.0)
    assert r["label"] == "real_vrp_prior"
    assert r["note"] == "prior, NOT a track record"
    assert r["window"]["trading_days"] == 34
    assert "max_drawdown_inr" in r["metrics"] and "cvar_5pct_inr" in r["metrics"]
    # tiny moves vs 13% implied → the premium seller is net positive here
    assert r["metrics"]["total_pnl_inr"] > 0
    assert r["vrp_audit"]["mean_realized_over_implied"] >= 0
