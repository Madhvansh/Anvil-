"""
Honest walk-forward backtest (candle-only, no look-ahead).

For each symbol and each day t with enough history:
  * compute features from candles[0..t]      (information available at t's close)
  * make the SAME directional decision the live model would
  * resolve against candles[t+1] close       (next-session realized move)
Accumulate calibration + paper P&L exactly as the live tracker does.

Honesty notes baked in:
  * The model uses FIXED priors set before this backtest was run — nothing is fitted to
    this data, so the whole history is effectively out-of-sample. We still report a recent
    HOLD-OUT slice separately to show the result isn't driven by one regime.
  * Index backtests are candle-only (no historical option chains), so they omit the small
    PCR tilt the live index model adds. Stocks are candle-only live too, so for stocks the
    backtest matches the live model exactly.
  * Costs are charged on every paper trade. Directional ceiling for daily moves is ~50-55%
    hit-rate; treat anything far above that with suspicion (likely look-ahead/overfit).
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone, timedelta

import config
from features import candle_features
from model import direction_score
from tips import _decide
from upstox_client import UpstoxClient

_IST = timezone(timedelta(hours=5, minutes=30))


def backtest_symbol(candles: list[dict], min_history: int = 60) -> list[dict]:
    closes = candles
    recs = []
    cost = config.PAPER_COST_BPS / 10000.0
    for t in range(min_history, len(closes) - 1):
        window = closes[: t + 1]
        feats = candle_features(window)
        if not feats.get("ok"):
            continue
        ds = direction_score(feats, None)
        direction, conf = _decide(ds["p_up"])
        if direction == "NEUTRAL":
            recs.append({"ts": closes[t]["ts"], "direction": "NEUTRAL"})
            continue
        entry = closes[t]["c"]
        exit_px = closes[t + 1]["c"]
        realized = exit_px / entry - 1.0
        up = exit_px > entry
        correct = 1 if ((direction == "UP" and up) or (direction == "DOWN" and not up)) else 0
        signed = realized if direction == "UP" else -realized
        recs.append({"ts": closes[t]["ts"], "direction": direction, "confidence": conf,
                     "correct": correct, "paper_return": signed - cost,
                     "brier": (conf - correct) ** 2})
    return recs


def aggregate(recs: list[dict], label: str = "") -> dict:
    d = [r for r in recs if r["direction"] != "NEUTRAL"]
    n = len(d)
    if not n:
        return {"label": label, "n": 0}
    hit = sum(r["correct"] for r in d) / n
    brier = sum(r["brier"] for r in d) / n
    rets = [r["paper_return"] for r in d]
    wins = [x for x in rets if x > 0]
    eq = 1.0
    for r in sorted(d, key=lambda x: x["ts"]):
        eq *= (1.0 + r["paper_return"])
    # reliability curve
    buckets = [(0.50, 0.55), (0.55, 0.60), (0.60, 0.65), (0.65, 1.01)]
    curve = []
    for lo, hi in buckets:
        sel = [r for r in d if lo <= r["confidence"] < hi]
        if sel:
            curve.append({"bucket": f"{int(lo*100)}-{min(int(hi*100),100)}%", "n": len(sel),
                          "stated": round(sum(s["confidence"] for s in sel) / len(sel), 3),
                          "actual": round(sum(s["correct"] for s in sel) / len(sel), 3)})
    return {
        "label": label, "n_directional": n, "n_abstain": len(recs) - n,
        "hit_rate": round(hit, 4), "brier": round(brier, 4),
        "win_rate": round(len(wins) / n, 4),
        "expectancy_pct": round(sum(rets) / n * 100, 4),
        "compounded_return_pct": round((eq - 1.0) * 100, 2),
        "reliability_curve": curve,
    }


def run(symbols=None, holdout_frac: float = 0.3) -> dict:
    client = UpstoxClient()
    indices = config.INDICES
    stocks = symbols if symbols is not None else config.stock_universe()
    all_recs, per_symbol = [], {}

    def do(sym, key, asset):
        try:
            candles = client.daily_candles(key, days=500)
            if len(candles) < 90:
                return
            recs = backtest_symbol(candles)
            per_symbol[sym] = aggregate(recs, sym)
            for r in recs:
                r["asset"] = asset
            all_recs.extend(recs)
            print(f"  {asset:5} {sym:12} decisions={len(recs):<4} "
                  f"hit={per_symbol[sym].get('hit_rate')} exp={per_symbol[sym].get('expectancy_pct')}%")
        except Exception as e:  # noqa: BLE001
            print(f"  ! {sym} failed: {type(e).__name__}: {str(e)[:100]}")

    print("Backtesting indices…")
    for name in indices:
        do(name, config.INDEX_INSTRUMENT_KEYS[name], "index")
    print("Backtesting stocks…")
    for sym in stocks:
        key = client.resolve_equity_key(sym)
        if key:
            do(sym, key, "stock")

    # chronological hold-out: most-recent slice only
    all_sorted = sorted([r for r in all_recs if r["direction"] != "NEUTRAL"], key=lambda x: x["ts"])
    cut = int(len(all_sorted) * (1 - holdout_frac))
    holdout = all_sorted[cut:]

    report = {
        "generated": datetime.now(_IST).isoformat(timespec="seconds"),
        "universe": {"indices": indices, "stocks": stocks, "horizon": "next_day (next session close)"},
        "overall": aggregate(all_recs, "ALL (full history, out-of-sample for fixed-prior model)"),
        "overall_indices": aggregate([r for r in all_recs if r.get("asset") == "index"], "indices"),
        "overall_stocks": aggregate([r for r in all_recs if r.get("asset") == "stock"], "stocks"),
        "recent_holdout": aggregate(holdout, f"recent {int(holdout_frac*100)}% hold-out"),
        "per_symbol": per_symbol,
        "honesty_note": (
            "Fixed-prior model (no parameters fitted to this data). Daily-direction hit-rates "
            "near 50-55% are expected and honest; the value is in calibration + abstention + "
            "position/band sizing, not in beating the directional ceiling. NOT investment advice."
        ),
        "disclaimer": config.DISCLAIMER,
    }
    return report


if __name__ == "__main__":
    rep = run()
    o = rep["overall"]; h = rep["recent_holdout"]
    print("\n===== BACKTEST SUMMARY =====")
    print(f"ALL: n={o['n_directional']} hit={o['hit_rate']} brier={o['brier']} "
          f"win={o['win_rate']} expectancy={o['expectancy_pct']}%/trade comp={o['compounded_return_pct']}%")
    print(f"  indices: hit={rep['overall_indices'].get('hit_rate')}  stocks: hit={rep['overall_stocks'].get('hit_rate')}")
    print(f"  recent hold-out: n={h.get('n_directional')} hit={h.get('hit_rate')} expectancy={h.get('expectancy_pct')}%")
    print("\nReliability (full history):")
    for b in o.get("reliability_curve", []):
        print(f"  {b['bucket']:>8}: n={b['n']:<5} stated={b['stated']:.3f} actual={b['actual']:.3f}")
    path = f"{config.REPORTS_DIR}/backtest_{datetime.now(_IST).strftime('%Y%m%d_%H%M%S')}.json"
    import os
    os.makedirs(config.REPORTS_DIR, exist_ok=True)
    json.dump(rep, open(path, "w"), indent=2)
    print(f"\nsaved → {os.path.basename(path)}")
