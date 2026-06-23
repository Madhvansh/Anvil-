"""
Tip tracker - the heart of Anvil Live.

Logs every tip when generated, then later RESOLVES it against the realized price at its
horizon and scores it two honest ways:

  1. CALIBRATION  - is the stated confidence truthful?
       reliability curve (confidence bucket -> actual hit-rate), Brier score, overall hit-rate.
  2. PAPER P&L    - what if you acted on the tip?
       enter at the tip price, exit at the horizon close, minus round-trip costs;
       win rate, expectancy, avg win/loss, total return, equity curve.

NEUTRAL (abstain) tips are logged but excluded from hit-rate and P&L. SQLite + stdlib only;
no look-ahead (resolution only uses post-horizon data).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone, timedelta

import calibration
import config

_IST = timezone(timedelta(hours=5, minutes=30))


def connect(db_path: str | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(db_path or config.DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE IF NOT EXISTS tips (
        tip_id TEXT PRIMARY KEY, created_ts TEXT, created_date TEXT, asset_class TEXT,
        symbol TEXT, instrument_key TEXT, horizon TEXT, direction TEXT, confidence REAL,
        raw_lean REAL, signal_status TEXT, edge_verified INTEGER, p_up REAL, entry_price REAL,
        target REAL, band_low REAL, band_high REAL, expected_move_pct REAL, rationale TEXT,
        model_version TEXT, provenance TEXT, features TEXT, status TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS outcomes (
        tip_id TEXT PRIMARY KEY, resolved_ts TEXT, exit_price REAL, realized_return REAL,
        direction_correct INTEGER, paper_return REAL, paper_pnl REAL, brier REAL, notes TEXT,
        FOREIGN KEY (tip_id) REFERENCES tips(tip_id))""")
    con.commit()
    return con


def log_tips(tips, db_path: str | None = None) -> int:
    con = connect(db_path)
    n = 0
    for t in tips:
        d = t.to_dict()
        params = {**d, "created_date": d["created_ts"][:10],
                  "features": json.dumps(d["features"]),
                  "signal_status": d["status"], "edge_verified": 1 if d["edge_verified"] else 0,
                  "lifecycle": "open"}
        try:
            con.execute("""INSERT OR IGNORE INTO tips
                (tip_id, created_ts, created_date, asset_class, symbol, instrument_key, horizon,
                 direction, confidence, raw_lean, signal_status, edge_verified, p_up, entry_price,
                 target, band_low, band_high, expected_move_pct, rationale, model_version,
                 provenance, features, status)
                VALUES
                (:tip_id,:created_ts,:created_date,:asset_class,:symbol,:instrument_key,:horizon,
                 :direction,:confidence,:raw_lean,:signal_status,:edge_verified,:p_up,:entry_price,
                 :target,:band_low,:band_high,:expected_move_pct,:rationale,:model_version,
                 :provenance,:features,:lifecycle)""", params)
            n += con.total_changes and 1 or 0
        except sqlite3.IntegrityError:
            pass
    con.commit()
    con.close()
    return n


def _exit_close_after(candles, created_date, horizon):
    if horizon == "intraday":
        same = [c for c in candles if c["ts"][:10] == created_date]
        return (same[-1]["ts"], same[-1]["c"]) if same else None
    after = [c for c in candles if c["ts"][:10] > created_date]
    return (after[0]["ts"], after[0]["c"]) if after else None


def resolve_open(client, db_path: str | None = None, verbose: bool = True) -> dict:
    con = connect(db_path)
    rows = con.execute("SELECT * FROM tips WHERE status='open'").fetchall()
    by_key = {}
    for r in rows:
        by_key.setdefault(r["instrument_key"], []).append(r)

    cost = config.PAPER_COST_BPS / 10000.0
    resolved = 0
    cache = {}
    for key, tip_rows in by_key.items():
        try:
            if key not in cache:
                cache[key] = client.daily_candles(key, days=40)
            candles = cache[key]
        except Exception as e:
            if verbose:
                print(f"  ! resolve fetch failed for {key}: {str(e)[:100]}")
            continue
        for r in tip_rows:
            ex = _exit_close_after(candles, r["created_date"], r["horizon"])
            if not ex:
                continue
            exit_ts, exit_price = ex
            entry = r["entry_price"]
            realized = (exit_price / entry - 1.0) if entry else 0.0
            direction = r["direction"]
            if direction == "NEUTRAL":
                correct, paper_ret, paper_pnl, brier = None, 0.0, 0.0, None
            else:
                up = exit_price > entry
                correct = 1 if ((direction == "UP" and up) or (direction == "DOWN" and not up)) else 0
                signed = realized if direction == "UP" else -realized
                paper_ret = signed - cost
                paper_pnl = paper_ret * config.PAPER_CAPITAL_PER_TIP
                brier = (r["confidence"] - correct) ** 2
            con.execute("INSERT OR REPLACE INTO outcomes VALUES (?,?,?,?,?,?,?,?,?)",
                (r["tip_id"], exit_ts, round(exit_price, 2), round(realized, 5),
                 correct, round(paper_ret, 5), round(paper_pnl, 2),
                 round(brier, 5) if brier is not None else None, f"resolved@{r['horizon']}"))
            con.execute("UPDATE tips SET status='resolved' WHERE tip_id=?", (r["tip_id"],))
            resolved += 1
    con.commit()
    con.close()
    if verbose:
        print(f"  resolved {resolved} tip(s)")
    return {"resolved": resolved}


def _reliability(rows):
    buckets = [(0.50, 0.55), (0.55, 0.60), (0.60, 0.65), (0.65, 1.01)]
    out = []
    for lo, hi in buckets:
        sel = [r for r in rows if r["direction_correct"] is not None and lo <= r["confidence"] < hi]
        if not sel:
            continue
        n = len(sel)
        out.append({"bucket": f"{int(lo*100)}-{int(hi*100) if hi<=1 else 100}%", "n": n,
                    "stated_conf": round(sum(r["confidence"] for r in sel) / n, 3),
                    "actual_hit_rate": round(sum(r["direction_correct"] for r in sel) / n, 3)})
    return out


def report(db_path: str | None = None) -> dict:
    con = connect(db_path)
    joined = con.execute("""SELECT t.*, o.direction_correct, o.realized_return, o.paper_return,
        o.paper_pnl, o.brier, o.exit_price, o.resolved_ts
        FROM tips t JOIN outcomes o ON o.tip_id=t.tip_id""").fetchall()
    open_n = con.execute("SELECT COUNT(*) FROM tips WHERE status='open'").fetchone()[0]
    total_tips = con.execute("SELECT COUNT(*) FROM tips").fetchone()[0]
    con.close()

    directional = [r for r in joined if r["direction_correct"] is not None]
    neutral = [r for r in joined if r["direction_correct"] is None]
    n_dir = len(directional)

    calib = {
        "resolved_directional": n_dir,
        "resolved_neutral_abstain": len(neutral),
        "hit_rate": round(sum(r["direction_correct"] for r in directional) / n_dir, 4) if n_dir else None,
        "brier_score": round(sum(r["brier"] for r in directional) / n_dir, 4) if n_dir else None,
        "mean_stated_confidence": round(sum(r["confidence"] for r in directional) / n_dir, 4) if n_dir else None,
        "reliability_curve": _reliability(directional),
    }

    pnl_returns = [r["paper_return"] for r in directional]
    wins = [x for x in pnl_returns if x > 0]
    losses = [x for x in pnl_returns if x <= 0]
    total_pnl = sum(r["paper_pnl"] for r in directional)
    eq = 1.0
    for r in sorted(directional, key=lambda x: x["resolved_ts"] or ""):
        eq *= (1.0 + r["paper_return"])
    paper = {
        "trades_taken": n_dir,
        "win_rate": round(len(wins) / n_dir, 4) if n_dir else None,
        "avg_win_pct": round(sum(wins) / len(wins) * 100, 3) if wins else None,
        "avg_loss_pct": round(sum(losses) / len(losses) * 100, 3) if losses else None,
        "expectancy_pct": round(sum(pnl_returns) / n_dir * 100, 4) if n_dir else None,
        "total_paper_pnl_inr": round(total_pnl, 2),
        "compounded_return_pct": round((eq - 1.0) * 100, 3) if n_dir else None,
        "capital_per_tip_inr": config.PAPER_CAPITAL_PER_TIP,
        "cost_bps_round_trip": config.PAPER_COST_BPS,
    }

    return {
        "generated": datetime.now(_IST).isoformat(timespec="seconds"),
        "edge_status": calibration.headline(),
        "totals": {"tips_logged": total_tips, "resolved": len(joined), "still_open": open_n},
        "calibration": calib,
        "paper_pnl": paper,
        "disclaimer": config.DISCLAIMER,
    }


def print_report(rep: dict) -> None:
    t = rep["totals"]; c = rep["calibration"]; p = rep["paper_pnl"]
    es = rep.get("edge_status", {})
    print("\n========== ANVIL LIVE - RELIABILITY REPORT ==========")
    print("EDGE STATUS: %s - %s" % ("VERIFIED" if es.get("edge_verified") else "NOT PROVEN", es.get("message", "")))
    print(f"tips logged={t['tips_logged']}  resolved={t['resolved']}  open={t['still_open']}")
    print("\n-- Calibration (are the confidences honest?) --")
    print(f"  directional resolved={c['resolved_directional']}  abstained={c['resolved_neutral_abstain']}")
    print(f"  hit-rate={c['hit_rate']}  Brier={c['brier_score']}  mean stated conf={c['mean_stated_confidence']}")
    for b in c["reliability_curve"]:
        print(f"    {b['bucket']:>8}: n={b['n']:<4} stated={b['stated_conf']:.3f} actual={b['actual_hit_rate']:.3f}")
    print("\n-- Paper P&L (what if you acted on every directional tip?) --")
    print(f"  trades={p['trades_taken']}  win_rate={p['win_rate']}  expectancy={p['expectancy_pct']}%/tip")
    print(f"  avg_win={p['avg_win_pct']}%  avg_loss={p['avg_loss_pct']}%  compounded={p['compounded_return_pct']}%")
    print(f"  total paper P&L=Rs.{p['total_paper_pnl_inr']} (Rs.{int(p['capital_per_tip_inr'])}/tip, {p['cost_bps_round_trip']}bps cost)")
    print("=====================================================")
