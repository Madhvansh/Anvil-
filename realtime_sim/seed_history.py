"""
Backfill DEMONSTRATION - prove the tracker's resolve + scoring path on real history.

Live tips can't resolve until their horizon elapses (tomorrow), so this seeds a SEPARATE
demo database with tips dated over the last N sessions - each built using ONLY candles up
to its decision date (no look-ahead) - then resolves them against the now-realized next
close. It populates a real calibration + paper-P&L report so you can see the heart work.

This is explicitly NOT the live forward track record (kept clean in tips.db). Provenance is
"backfill_demo" and it writes to a separate DB. Read-only market data; analytics only.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone, timedelta

import config
import tracker
from features import candle_features, chain_features
from tips import _build
from upstox_client import UpstoxClient

_IST = timezone(timedelta(hours=5, minutes=30))
DEMO_DB = os.path.join("/tmp/anvil_rt", "seed_demo.db") if os.path.isdir("/tmp/anvil_rt") \
    else os.path.join(config.REPORTS_DIR, "seed_demo.db")


def seed(n_sessions: int = 15):
    client = UpstoxClient()
    symbols = [("index", s, config.INDEX_INSTRUMENT_KEYS[s]) for s in config.INDICES]
    for s in config.stock_universe():
        k = client.resolve_equity_key(s)
        if k:
            symbols.append(("stock", s, k))

    all_tips = []
    for asset, sym, key in symbols:
        try:
            candles = client.daily_candles(key, days=200)
        except Exception as e:
            print(f"  ! {sym} fetch failed: {str(e)[:80]}"); continue
        if len(candles) < 80:
            continue
        # decision points: the last n_sessions completed days that still have a NEXT close
        for t in range(len(candles) - n_sessions - 1, len(candles) - 1):
            window = candles[: t + 1]
            feats = candle_features(window)
            if not feats.get("ok"):
                continue
            created_ts = candles[t]["ts"][:10] + "T15:30:00+05:30"
            entry = candles[t]["c"]
            tip = _build(sym, asset, key, entry, feats, None, "next_day", created_ts)
            all_tips.append(tip)

    n = tracker.log_tips(all_tips, db_path=DEMO_DB)
    print(f"seeded {n} backfilled tips into {os.path.basename(DEMO_DB)} (provenance demo)")
    tracker.resolve_open(client, db_path=DEMO_DB)
    rep = tracker.report(db_path=DEMO_DB)
    print("\n*** BACKFILL DEMONSTRATION (not the live track record) ***")
    tracker.print_report(rep)
    import json
    out = os.path.join(config.REPORTS_DIR, "seed_demo_report.json")
    os.makedirs(config.REPORTS_DIR, exist_ok=True)
    with open(out, "w") as f:
        json.dump(rep, f, indent=2)
    print("saved ->", os.path.basename(out))
    return rep


if __name__ == "__main__":
    rm = "--fresh" in sys.argv
    if rm and os.path.exists(DEMO_DB):
        os.remove(DEMO_DB)
    seed()
