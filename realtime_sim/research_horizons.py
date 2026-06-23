"""
Honest research probe — WHERE (if anywhere) is there cost-aware signal?

Pre-registered, literature-motivated tests (no cherry-picking after the fact):
  * time-series momentum: signal = sign(return over `lookback`), held `horizon` days
  * cross-sectional momentum: each day, long the top-K and short the bottom-K names ranked
    by `lookback` return, held `horizon` days (market-neutral)
Standard momentum lookbacks {5,10,20,60} × horizons {1,5,10,20}. Costs charged every trade.

We report hit-rate and NET expectancy for each cell and say plainly what works and what
doesn't. Daily direction (~50%) is expected to be the weakest; the question is whether
slower/cross-sectional momentum clears costs. NOT investment advice.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta

import config
from upstox_client import UpstoxClient

_IST = timezone(timedelta(hours=5, minutes=30))
COST = config.PAPER_COST_BPS / 10000.0


def _load_all() -> dict[str, list[dict]]:
    c = UpstoxClient()
    series = {}
    syms = config.INDICES + config.stock_universe()
    for s in syms:
        key = config.INDEX_INSTRUMENT_KEYS.get(s) or c.resolve_equity_key(s)
        if not key:
            continue
        try:
            cs = c.daily_candles(key, days=500)
            if len(cs) > 120:
                series[s] = cs
        except Exception:
            pass
    return series


def timeseries(series, lookback, horizon):
    hits = n = 0
    rets = []
    for s, cs in series.items():
        closes = [x["c"] for x in cs]
        for t in range(lookback, len(closes) - horizon):
            mom = closes[t] / closes[t - lookback] - 1.0
            if abs(mom) < 1e-9:
                continue
            sign = 1 if mom > 0 else -1
            fwd = closes[t + horizon] / closes[t] - 1.0
            net = sign * fwd - COST
            rets.append(net)
            hits += 1 if (sign * fwd) > 0 else 0
            n += 1
    if not n:
        return None
    return {"n": n, "hit": round(hits / n, 4), "exp_net_%": round(sum(rets) / n * 100, 4),
            "exp_ann_%": round(sum(rets) / n / horizon * 252 * 100, 2)}


def cross_sectional(series, lookback, horizon, k=5):
    # align by date intersection
    syms = list(series.keys())
    dates = set.intersection(*[{x["ts"][:10] for x in series[s]} for s in syms])
    dates = sorted(dates)
    idx = {s: {x["ts"][:10]: x["c"] for x in series[s]} for s in syms}
    leg_rets = []
    for i in range(lookback, len(dates) - horizon):
        d0, dpast, dfwd = dates[i], dates[i - lookback], dates[i + horizon]
        moms = []
        for s in syms:
            if d0 in idx[s] and dpast in idx[s] and dfwd in idx[s]:
                moms.append((s, idx[s][d0] / idx[s][dpast] - 1.0))
        if len(moms) < 2 * k:
            continue
        moms.sort(key=lambda z: z[1])
        shorts = moms[:k]; longs = moms[-k:]
        long_r = sum(idx[s][dfwd] / idx[s][d0] - 1.0 for s, _ in longs) / k
        short_r = sum(idx[s][dfwd] / idx[s][d0] - 1.0 for s, _ in shorts) / k
        leg_rets.append((long_r - short_r) - 2 * COST)  # both legs cost
    if not leg_rets:
        return None
    return {"rebalances": len(leg_rets), "exp_net_%": round(sum(leg_rets) / len(leg_rets) * 100, 4),
            "exp_ann_%": round(sum(leg_rets) / len(leg_rets) / horizon * 252 * 100, 2)}


def main():
    series = _load_all()
    print(f"loaded {len(series)} symbols\n")
    out = {"time_series": {}, "cross_sectional": {}}
    print("TIME-SERIES MOMENTUM (hit / net exp%/trade / annualized%)")
    for lb in (5, 10, 20, 60):
        for h in (1, 5, 10, 20):
            r = timeseries(series, lb, h)
            if r:
                out["time_series"][f"lb{lb}_h{h}"] = r
                print(f"  lookback={lb:<2} horizon={h:<2}: hit={r['hit']:.3f} "
                      f"net={r['exp_net_%']:+.4f}%/trade ann={r['exp_ann_%']:+.1f}%")
    print("\nCROSS-SECTIONAL MOMENTUM (long top5 / short bottom5, market-neutral)")
    for lb in (5, 10, 20, 60):
        for h in (5, 10, 20):
            r = cross_sectional(series, lb, h, k=5)
            if r:
                out["cross_sectional"][f"lb{lb}_h{h}"] = r
                print(f"  lookback={lb:<2} horizon={h:<2}: net={r['exp_net_%']:+.4f}%/rebal "
                      f"ann={r['exp_ann_%']:+.1f}%  (n={r['rebalances']})")
    import os
    os.makedirs(config.REPORTS_DIR, exist_ok=True)
    path = os.path.join(config.REPORTS_DIR, f"research_horizons_{datetime.now(_IST).strftime('%Y%m%d_%H%M%S')}.json")
    json.dump(out, open(path, "w"), indent=2)
    print(f"\nsaved → {os.path.basename(path)}")
    return out


if __name__ == "__main__":
    main()
