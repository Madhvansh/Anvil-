"""
Anvil Live - orchestrator.

One run: pull live data -> generate tips for indices + stocks -> log them -> resolve any
previously-open tips now due -> print + save a snapshot and the reliability report.

    python run.py                      # default universe + primary horizon
    python run.py --horizon intraday   # today-close tips
    python run.py --no-resolve         # just generate + log

Read-only. No orders. Analytics & education only - see config.DISCLAIMER.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone, timedelta

import calibration
import config
import tracker
from tips import generate_tips
from upstox_client import UpstoxClient

_IST = timezone(timedelta(hours=5, minutes=30))


def main(argv):
    horizon = config.PRIMARY_HORIZON
    do_resolve = "--no-resolve" not in argv
    if "--horizon" in argv:
        horizon = argv[argv.index("--horizon") + 1]

    client = UpstoxClient()
    print("Anvil Live - generating %s tips for %d indices + %d stocks..."
          % (horizon, len(config.INDICES), len(config.stock_universe())))
    tips = generate_tips(client, horizon=horizon)
    n_new = tracker.log_tips(tips)

    actionable = sorted([t for t in tips if t.status == "ACTIONABLE"], key=lambda t: t.confidence, reverse=True)
    watch = sorted([t for t in tips if t.status == "WATCH"], key=lambda t: t.confidence, reverse=True)
    abstained = [t for t in tips if t.status == "ABSTAIN"]

    eh = calibration.headline()
    print("\nEDGE STATUS: %s - %s" % ("VERIFIED" if eh.get("edge_verified") else "NOT PROVEN", eh.get("message", "")))
    print("\n%d ACTIONABLE | %d WATCH (lean, unproven) | %d ABSTAIN" % (len(actionable), len(watch), len(abstained)))
    for label, group in (("ACTIONABLE", actionable), ("WATCH", watch)):
        for t in group:
            arrow = "UP " if t.direction == "UP" else "DN "
            print("  [%-10s] %s %-5s %-12s cal_conf=%2.0f%% (raw %2.0f%%) @%-10s target=%s band=[%s,%s] (%.2f%% sd)"
                  % (label, arrow, t.asset_class, t.symbol, t.confidence * 100, t.raw_lean * 100,
                     t.entry_price, t.target, t.band_low, t.band_high, t.expected_move_pct))
    if abstained:
        print("  ABSTAIN: " + ", ".join(t.symbol for t in abstained))

    if do_resolve:
        print("\nResolving any due open tips...")
        tracker.resolve_open(client)

    os.makedirs(config.REPORTS_DIR, exist_ok=True)
    stamp = datetime.now(_IST).strftime("%Y%m%d_%H%M%S")
    snap = {"generated": datetime.now(_IST).isoformat(timespec="seconds"),
            "horizon": horizon, "edge_status": eh,
            "tips": [t.to_dict() for t in tips], "disclaimer": config.DISCLAIMER}
    snap_path = os.path.join(config.REPORTS_DIR, "tips_%s.json" % stamp)
    with open(snap_path, "w") as f:
        json.dump(snap, f, indent=2)

    rep = tracker.report()
    tracker.print_report(rep)
    rep_path = os.path.join(config.REPORTS_DIR, "reliability_%s.json" % stamp)
    with open(rep_path, "w") as f:
        json.dump(rep, f, indent=2)
    print("\nsaved: %s (tips), %s (reliability)" % (os.path.basename(snap_path), os.path.basename(rep_path)))
    print("new tips logged this run: %d" % n_new)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
