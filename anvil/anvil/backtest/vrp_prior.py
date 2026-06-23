"""Phase 5 — the VRP-harvest PRIOR (real, non-circular, no look-ahead).

Ported from the v2 sim (``realtime_sim/backtest_v2.py``) into anvil, reading anvil's Yahoo cache.
Upstox serves no historical option chains, so a real backtest of the live multi-leg STRUCTURES is
impossible. What we CAN measure cleanly and causally is the edge they harvest — the variance risk
premium — with REAL data, nothing fitted:

  * IMPLIED  = India VIX close on day t  (published, point-in-time — known at t)
  * REALIZED = the actual NIFTY move from close t → close t+1

Each day SELL a 1-day ATM straddle priced at the VIX-implied vol; settle against the real next-day
move, net of a conservative cost on the premium. PARAMETER-FREE, strictly causal, ~2y incl. stress.

It is the EDGE PRIOR (labeled ``real_vrp_prior``), explicitly NOT a track record of live tips (those
accrue forward in the ledger). Short-vol: it wins most days then loses big on gaps — read maxDD /
worst-day / CVaR, never the win-rate alone.
"""

from __future__ import annotations

import math

from ..ingest import yahoo

_TD = 252.0
_STRADDLE_K = math.sqrt(2.0 / math.pi)  # ATM straddle premium ≈ 0.7979 · S · σ · √T
_COST_FRAC_OF_PREMIUM = 0.06  # conservative round-trip cost as a fraction of premium (2 legs)


def _closes(symbol: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for b in yahoo.read_cache(symbol):
        try:
            out[str(b["date"])[:10]] = float(b["c"])
        except (KeyError, ValueError, TypeError):
            continue
    return out


def _tail_block(pnls_inr: list[float], capital: float) -> dict:
    n = len(pnls_inr)
    if n == 0:
        return {"n": 0}
    wins = [p for p in pnls_inr if p > 0]
    losses = [p for p in pnls_inr if p <= 0]
    total = sum(pnls_inr)
    mean = total / n
    sd = math.sqrt(sum((p - mean) ** 2 for p in pnls_inr) / (n - 1)) if n > 1 else 0.0
    downside = [p for p in pnls_inr if p < 0]
    dsd = math.sqrt(sum(p * p for p in downside) / len(downside)) if downside else 0.0
    eq, peak, max_dd = 0.0, 0.0, 0.0
    for p in pnls_inr:
        eq += p
        peak = max(peak, eq)
        max_dd = min(max_dd, eq - peak)
    k = max(1, int(math.ceil(0.05 * n)))
    cvar = sum(sorted(pnls_inr)[:k]) / k
    gp, gl = sum(wins), -sum(losses)
    sharpe = (mean / sd * math.sqrt(_TD)) if sd > 0 else None
    sortino = (mean / dsd * math.sqrt(_TD)) if dsd > 0 else None
    return {
        "n": n,
        "win_rate": round(len(wins) / n, 4),
        "mean_pnl_inr_per_day": round(mean, 2),
        "total_pnl_inr": round(total, 2),
        "return_on_capital_pct": round(total / capital * 100, 2),
        "annualized_return_pct": round(mean * _TD / capital * 100, 2),
        "profit_factor": round(gp / gl, 3) if gl > 0 else None,
        "sharpe": round(sharpe, 3) if sharpe is not None else None,
        "sortino": round(sortino, 3) if sortino is not None else None,
        # --- TAIL (the whole point) ---
        "max_drawdown_inr": round(max_dd, 2),
        "max_drawdown_pct": round(max_dd / capital * 100, 2),
        "worst_day_inr": round(min(pnls_inr), 2),
        "cvar_5pct_inr": round(cvar, 2),
        "calmar": round(total / abs(max_dd), 3) if max_dd < 0 else None,
    }


def run_vrp_prior(capital: float = 1_000_000.0, index_symbol: str = "^NSEI",
                  vix_symbol: str = "^INDIAVIX") -> dict:
    """The non-circular VRP edge prior off anvil's Yahoo cache. Degrades gracefully when the cache is
    absent (run ``anvil data fetch-closes --symbols ^NSEI,^INDIAVIX`` first)."""
    idx, vix = _closes(index_symbol), _closes(vix_symbol)
    dates = sorted(set(idx) & set(vix))
    if len(dates) < 30:
        return {"error": "insufficient history", "n_dates": len(dates),
                "hint": "run `anvil data fetch-closes --symbols ^NSEI,^INDIAVIX`"}

    pnls_inr: list[float] = []
    realized_over_implied: list[float] = []
    inverted = 0
    notional = capital
    for i in range(len(dates) - 1):
        d, dn = dates[i], dates[i + 1]
        sigma_ann = vix[d] / 100.0
        sigma_day = sigma_ann / math.sqrt(_TD)
        premium_frac = _STRADDLE_K * sigma_day
        move_frac = abs(idx[dn] / idx[d] - 1.0)
        net_frac = (premium_frac - move_frac) - premium_frac * _COST_FRAC_OF_PREMIUM
        pnls_inr.append(net_frac * notional)
        realized_ann = move_frac * math.sqrt(_TD) / _STRADDLE_K
        realized_over_implied.append(realized_ann / sigma_ann if sigma_ann else 0.0)
        if realized_ann > sigma_ann:
            inverted += 1

    n = len(pnls_inr)
    return {
        "label": "real_vrp_prior",
        "note": "prior, NOT a track record",
        "method": ("PARAMETER-FREE daily ATM-straddle SELL on NIFTY; IMPLIED=India VIX close[t], "
                   "REALIZED=actual NIFTY close[t]→[t+1]; no look-ahead, nothing fitted; cost = "
                   f"{int(_COST_FRAC_OF_PREMIUM * 100)}% of premium."),
        "window": {"start": dates[0], "end": dates[-1], "trading_days": n},
        "capital_inr": capital,
        "metrics": _tail_block(pnls_inr, capital),
        "vrp_audit": {
            "mean_realized_over_implied": round(sum(realized_over_implied) / len(realized_over_implied), 3),
            "days_realized_exceeded_implied": inverted,
            "pct_days_vrp_inverted": round(inverted / n * 100, 1),
        },
        "honesty": ("The cleanest causal measure of NIFTY's variance risk premium (real VIX vs real "
                    "realized). Selling insurance: wins most days, loses big on gaps — read maxDD / "
                    "worst-day / CVaR, never the win-rate alone. The live structures' edge accrues "
                    "FORWARD in the ledger and is gate-bound; this prior never short-circuits Gate-0."),
    }
