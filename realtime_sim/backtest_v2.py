"""Anvil Live v2 — the VRP-harvest backtest (real, non-circular, no look-ahead).

The honest problem (adversary #5): Upstox serves NO historical option chains, so a real backtest
of the live multi-leg STRUCTURES is impossible. What we CAN measure — cleanly and causally — is the
underlying edge those structures harvest: the variance risk premium. We do it with REAL historical
data, not a reconstructed smile:

  * IMPLIED  = India VIX close on day t  (a published, point-in-time implied-vol index — known at t)
  * REALIZED = the actual NIFTY move from close t → close t+1

Each day we SELL a 1-day ATM straddle priced at the VIX-implied vol and settle it against the real
next-day move, net of a conservative cost on the premium. This is PARAMETER-FREE (nothing is fitted),
strictly causal (VIX[t] and ret[t+1]), and spans a ~2-year window that INCLUDES real stress days —
so the tail is real, not assumed.

It is the VRP PRIOR, explicitly NOT a track record of the live structures (those accrue forward in
tips_v2.db). Labeled 'real_vrp_prior' so it is never confused with live-resolved P&L.
"""
from __future__ import annotations

import csv
import math
import os

import config

_HERE = os.path.dirname(os.path.abspath(__file__))
_CACHE = os.path.join(_HERE, "..", "anvil", "data", "closes_cache")
_TD = 252.0
# ATM straddle ≈ 0.7979 · S · σ · √T  (Black, ATM, r≈0). Premium the seller collects.
_STRADDLE_K = math.sqrt(2.0 / math.pi)  # ≈ 0.7979
# Conservative round-trip cost as a FRACTION OF PREMIUM (2 legs spread-crossing + statutory).
_COST_FRAC_OF_PREMIUM = 0.06


def _load_closes(fname: str) -> list[tuple[str, float]]:
    path = os.path.join(_CACHE, fname)
    out = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            try:
                out.append((row["date"], float(row["c"])))
            except (KeyError, ValueError):
                continue
    out.sort(key=lambda x: x[0])
    return out


def _tail_block(pnls_inr: list, capital: float) -> dict:
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
    sharpe = (mean / sd * math.sqrt(_TD)) if sd > 0 else None      # per-trade≈daily → annualize
    sortino = (mean / dsd * math.sqrt(_TD)) if dsd > 0 else None
    return {
        "n": n,
        "win_rate": round(len(wins) / n, 4),
        "mean_pnl_inr_per_day": round(mean, 2),
        "total_pnl_inr": round(total, 2),
        "return_on_capital_pct": round(total / capital * 100, 2),
        "annualized_return_pct": round(mean * _TD / capital * 100, 2),
        "avg_win_inr": round(sum(wins) / len(wins), 2) if wins else None,
        "avg_loss_inr": round(sum(losses) / len(losses), 2) if losses else None,
        "profit_factor": round(gp / gl, 3) if gl > 0 else None,
        "sharpe": round(sharpe, 3) if sharpe is not None else None,
        "sortino": round(sortino, 3) if sortino is not None else None,
        # --- TAIL (the whole point) ---
        "max_drawdown_inr": round(max_dd, 2),
        "max_drawdown_pct": round(max_dd / capital * 100, 2),
        "worst_day_inr": round(min(pnls_inr), 2),
        "worst_day_pct": round(min(pnls_inr) / capital * 100, 3),
        "cvar_5pct_inr": round(cvar, 2),
        "calmar": round(total / abs(max_dd), 3) if max_dd < 0 else None,
    }


def run_vrp_backtest(capital: float | None = None, index_file: str = "_NSEI.csv",
                     vix_file: str = "_INDIAVIX.csv") -> dict:
    capital = capital or config.V2_CAPITAL
    idx = dict(_load_closes(index_file))
    vix = dict(_load_closes(vix_file))
    dates = sorted(set(idx) & set(vix))
    if len(dates) < 30:
        return {"error": "insufficient history", "n_dates": len(dates)}

    pnls_inr = []
    vrp_inverted_days = 0
    realized_over_implied = []
    daily = []
    notional = capital  # one straddle per day on the full notional book (illustrative scale)
    for i in range(len(dates) - 1):
        d, dn = dates[i], dates[i + 1]
        s0, s1 = idx[d], idx[dn]
        sigma_ann = vix[d] / 100.0
        sigma_day = sigma_ann / math.sqrt(_TD)
        premium_frac = _STRADDLE_K * sigma_day           # premium as fraction of spot (1-day ATM straddle)
        move_frac = abs(s1 / s0 - 1.0)                   # realized 1-day move
        gross_frac = premium_frac - move_frac            # seller P&L as fraction of spot
        cost_frac = premium_frac * _COST_FRAC_OF_PREMIUM
        net_frac = gross_frac - cost_frac
        pnl_inr = net_frac * notional
        pnls_inr.append(pnl_inr)
        daily.append({"date": dn, "premium_pct": round(premium_frac * 100, 3),
                      "move_pct": round(move_frac * 100, 3), "net_pct": round(net_frac * 100, 4)})
        # VRP audit: realized vs implied (annualized). A single |daily move| is E|r|=σ·√(2/π), so to
        # compare like-for-like with implied σ we de-bias by /√(2/π) (=_STRADDLE_K). This RAISES the
        # ratio (less flattering to sellers) — honest (#5). NB: this only affects the audit diagnostic,
        # never the P&L (which uses the real premium vs the real move).
        realized_ann = move_frac * math.sqrt(_TD) / _STRADDLE_K
        realized_over_implied.append(realized_ann / sigma_ann if sigma_ann else 0.0)
        if realized_ann > sigma_ann:
            vrp_inverted_days += 1

    m = _tail_block(pnls_inr, capital)
    n = len(pnls_inr)
    stress_days = sorted(pnls_inr)[:max(1, n // 50)]  # worst ~2%
    return {
        "label": "real_vrp_prior",
        "method": ("PARAMETER-FREE daily ATM-straddle SELL on NIFTY. IMPLIED=India VIX close[t] "
                   "(published, point-in-time), REALIZED=actual NIFTY close[t]→[t+1]. No look-ahead, "
                   "nothing fitted. Cost = %.0f%% of premium (2 legs, spread + statutory). NOT a "
                   "backtest of the live structures (no historical chains exist) — it measures the "
                   "VRP edge those structures harvest." % (_COST_FRAC_OF_PREMIUM * 100)),
        "window": {"start": dates[0], "end": dates[-1], "trading_days": n},
        "capital_inr": capital,
        "metrics": m,
        "vrp_audit": {
            "mean_realized_over_implied": round(sum(realized_over_implied) / len(realized_over_implied), 3),
            "days_realized_exceeded_implied": vrp_inverted_days,
            "pct_days_vrp_inverted": round(vrp_inverted_days / n * 100, 1),
            "interpretation": ("realized < implied on most days (ratio<1) ⇒ premium-selling has a real, "
                               "positive expected edge here; the loss days are the tail you must survive."),
        },
        "worst_2pct_days_inr": [round(x, 2) for x in stress_days],
        "honesty": ("This is the EDGE PRIOR, not a track record. It is the cleanest causal measurement "
                    "of NIFTY's variance risk premium with real implied (VIX) and real realized data. "
                    "It still selling-insurance: it wins most days, then loses big on gaps — read maxDD, "
                    "worst-day and CVaR, never the win-rate alone."),
        "disclaimer": config.V2_DISCLAIMER,
    }


def print_backtest(rep: dict) -> None:
    if rep.get("error"):
        print("VRP backtest error:", rep["error"])
        return
    m = rep["metrics"]
    w = rep["window"]
    va = rep["vrp_audit"]
    print("\n============ ANVIL LIVE v2 — VRP HARVEST BACKTEST (real, non-circular) ============")
    print(rep["method"])
    print(f"\nwindow {w['start']} → {w['end']}  ({w['trading_days']} trading days)  on ₹{int(rep['capital_inr']):,} notional")
    print(f"  win_rate={m['win_rate']}  mean=₹{m['mean_pnl_inr_per_day']}/day  total=₹{m['total_pnl_inr']:,}  "
          f"({m['return_on_capital_pct']}% on capital, ~{m['annualized_return_pct']}%/yr)")
    print(f"  Sharpe={m['sharpe']}  Sortino={m['sortino']}  Profit-factor={m['profit_factor']}")
    print(f"  TAIL: maxDD=₹{m['max_drawdown_inr']:,} ({m['max_drawdown_pct']}%)  worst_day=₹{m['worst_day_inr']:,} "
          f"({m['worst_day_pct']}%)  CVaR5%=₹{m['cvar_5pct_inr']:,}  Calmar={m['calmar']}")
    print(f"  VRP audit: mean realized/implied={va['mean_realized_over_implied']}  "
          f"VRP-inverted days={va['days_realized_exceeded_implied']} ({va['pct_days_vrp_inverted']}%)")
    print("  " + rep["honesty"])
    print("==================================================================================")


if __name__ == "__main__":
    print_backtest(run_vrp_backtest())
