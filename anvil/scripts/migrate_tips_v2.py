"""One-shot migration: fold the v2 sim's accrued live measurements (``realtime_sim/tips_v2.db``) into
anvil's ledger + IssuedTipStore, then RECONCILE. Read-only on the source.

Run this as the first step of the Phase-5 "migrate → revalidate → review" retirement of realtime_sim
(the user's chosen path). After it reconciles, run ``anvil ledger run-daily --full`` (which calls
``revalidate_from_live``) and then INSPECT the gate0 report / ``/api/tips/trust-dial`` BEFORE relying
on any newly-armed emission — migrated real evidence can legitimately certify a cell and arm the wall.
Only after that review should ``realtime_sim/`` be deleted.

Usage:
    .venv/Scripts/python scripts/migrate_tips_v2.py --src ../realtime_sim/tips_v2.db [--commit]

Without ``--commit`` it does a DRY RUN (counts + reconciliation preview, writes nothing).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from anvil.ledger.ledger import CalibrationLedger  # noqa: E402
from anvil.tips.calibration import record_tip  # noqa: E402
from anvil.tips.store import IssuedTipStore  # noqa: E402
from anvil.tips.types import HEADLINE, WATCHLIST, Tip  # noqa: E402

_SYNTHETIC = {"upstox_live"}  # provenance that maps to the real 'tip_live' source class


def _tip_from_v2_row(r: sqlite3.Row) -> Tip:
    """Reconstruct an anvil Tip from a v2 ``strat_tips`` row, preserving the source firewall."""
    legs = json.loads(r["legs"]) if r["legs"] else []
    breakevens = json.loads(r["breakevens"]) if r["breakevens"] else []
    source = "tip_live" if (r["provenance"] or "") in _SYNTHETIC else "demo"
    edge = float(r["edge_prob"] or 0.0)
    gross = float(r["ev_gross"] or 0.0)
    cost = float(r["cost_rt"] or 0.0)
    return Tip(
        underlying=r["underlying"], created_ts=r["created_ts"], resolve_ts=r["expiry"],
        horizon_days=float(r["horizon_days"] or 0.0), structure=r["strategy"], direction=r["direction"],
        legs=legs, conviction=edge, edge_prob=edge, gross_ev=gross, round_trip_cost=cost,
        cost_adjusted_ev=float(r["ev_net"] or (gross - cost)), max_loss=float(r["max_loss"] or 0.0),
        max_profit=(float(r["max_profit"]) if r["max_profit"] is not None else None),
        entry_debit_credit=float(r["net_credit"] or 0.0), lot_size=int(r["lot_size"] or 1),
        breakevens=breakevens, regime_at_issue=r["regime"] or "", regime_bucket=r["regime"] or "",
        tier=WATCHLIST if r["status"] != "ACTIONABLE" else HEADLINE, source=source,
        model_version=r["model_version"] or "anvil-live-v2",
    )


def migrate(src: str, *, commit: bool) -> dict:
    con = sqlite3.connect(src)
    con.row_factory = sqlite3.Row
    tips = con.execute("SELECT * FROM strat_tips WHERE action='TRADE'").fetchall()
    outcomes = {o["tip_id"]: o for o in con.execute("SELECT * FROM strat_outcomes").fetchall()}
    con.close()

    led = CalibrationLedger()
    istore = IssuedTipStore()
    migrated = resolved = 0
    id_map: dict[str, str] = {}  # v2 tip_id -> anvil tip_id
    try:
        for r in tips:
            tip = _tip_from_v2_row(r)
            id_map[r["tip_id"]] = tip.tip_id
            if commit:
                record_tip(led, tip, spot=float(r["spot_entry"] or 0.0), forward=float(r["spot_entry"] or 0.0))
                istore.record(tip)
            migrated += 1
            o = outcomes.get(r["tip_id"])
            if o is not None:
                net = float(o["pnl_final"] or 0.0)
                ret = float(o["ret_on_risk"] or 0.0)
                outcome = int(o["win"] or 0)
                if commit:
                    fid = tip.ledger_forecast_id
                    if fid:
                        try:
                            led.resolve(fid, 1.0 if outcome else -1.0, resolved_ts=o["resolved_ts"])
                        except KeyError:
                            pass
                    istore.mark_resolved(tip.tip_id, outcome, o["resolved_ts"], net_pnl=net, ret=ret)
                resolved += 1
        # Reconciliation
        recon = {"v2_trade_tips": len(tips), "v2_resolved": len(outcomes), "migrated": migrated,
                 "resolved": resolved, "matched_resolved": sum(1 for t in id_map if t in outcomes)}
        recon["ok"] = (recon["resolved"] == recon["matched_resolved"])
        return {"committed": commit, "reconciliation": recon}
    finally:
        led.close()
        istore.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(ROOT.parent / "realtime_sim" / "tips_v2.db"))
    ap.add_argument("--commit", action="store_true", help="actually write (default: dry run)")
    args = ap.parse_args()
    if not Path(args.src).exists():
        print(f"source not found: {args.src}")
        return 1
    res = migrate(args.src, commit=args.commit)
    print(json.dumps(res, indent=2))
    if not res["reconciliation"]["ok"]:
        print("RECONCILIATION MISMATCH — do not trust the migration; investigate before deleting realtime_sim.")
        return 2
    if not args.commit:
        print("\nDRY RUN ok. Re-run with --commit, then `anvil ledger run-daily --full`, then REVIEW the "
              "gate0 report / trust-dial BEFORE relying on any newly-armed emission.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
