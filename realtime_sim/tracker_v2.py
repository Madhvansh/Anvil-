"""Anvil Live v2 — strategy-tip tracker + honest scorecard (SQLite, pure stdlib).

Logs every ranked option-structure idea, resolves it at its horizon (option expiry settlement)
against the REALIZED underlying path, and scores it the honest way:

  * Paper P&L through the FULL India F&O cost stack (costs_v2), spread-crossing fills.
  * TAIL stats are MANDATORY for premium-selling (adversary #1/#10): max drawdown, worst day,
    worst trade, CVaR(5%), Calmar, Sortino — win-rate/expectancy is NEVER shown alone.
  * MAE/MFE + a MODELED STOP (adversary #2): a trade that breached its stop intraday is booked at
    the stop, not flattered by a favourable close. The close-vs-stop gap is reported.
  * VRP audit (adversary #3): realized_vol/atm_iv at entry vs resolution, so the thesis is measured.
  * Open trades are EXCLUDED from stats but COUNTED prominently (adversary #12) — open ≠ flat.
  * Benchmark (adversary #16): every class is shown beside a do-nothing CASH line.
  * Edge is MEASURED, never asserted; ACTIONABLE only when a class clears the bar (adversary #17).

Read-only: resolution uses only post-horizon market data; no order is ever placed.
"""
from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime, timedelta, timezone

import config
import costs_v2
import engine_v2

_IST = timezone(timedelta(hours=5, minutes=30))
MODEL_VERSION = "anvil-live-v2-vrp-1.0.0"


def connect(db_path: str | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(db_path or config.V2_DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE IF NOT EXISTS strat_tips (
        tip_id TEXT PRIMARY KEY, created_ts TEXT, created_date TEXT, asset_class TEXT,
        underlying TEXT, instrument_key TEXT, strategy TEXT, direction TEXT, regime TEXT,
        defined_risk INTEGER, regime_kind TEXT, expiry TEXT, horizon_days REAL, spot_entry REAL, atm_iv REAL,
        realized_vol REAL, vrp_ratio REAL, vrp_signal TEXT, lot_size INTEGER, units INTEGER,
        edge_prob REAL, calibrated_edge REAL, ev_gross REAL, ev_net REAL, cost_rt REAL,
        max_loss REAL, max_profit REAL, net_credit REAL, breakevens TEXT, legs TEXT,
        liquidity REAL, status TEXT, action TEXT, gate_reasons TEXT, score REAL,
        model_version TEXT, provenance TEXT, lifecycle TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS strat_outcomes (
        tip_id TEXT PRIMARY KEY, resolved_ts TEXT, terminal_spot REAL, pnl_close REAL,
        pnl_stopped REAL, pnl_final REAL, ret_on_risk REAL, win INTEGER, profitable_close INTEGER,
        mae REAL, mfe REAL, stop_hit INTEGER, vrp_at_resolution REAL, realized_vol_window REAL,
        notes TEXT, FOREIGN KEY (tip_id) REFERENCES strat_tips(tip_id))""")
    con.commit()
    return con


def _mk_id(underlying, strategy, expiry, created_ts) -> str:
    import hashlib
    return hashlib.sha1(f"{underlying}|{strategy}|{expiry}|{created_ts}".encode()).hexdigest()[:16]


def log_evals(evals: list[dict], market_states: dict, created_ts: str | None = None,
              db_path: str | None = None) -> int:
    """Log ranked evaluations (all of them — TRADE and ABSTAIN — for honest abstention accounting)."""
    con = connect(db_path)
    created_ts = created_ts or datetime.now(_IST).isoformat(timespec="seconds")
    n = 0
    for e in evals:
        s = e["structure"]
        ms = market_states[s.underlying]
        tip_id = _mk_id(s.underlying, s.strategy, ms.expiry, created_ts)
        row = {
            "tip_id": tip_id, "created_ts": created_ts, "created_date": created_ts[:10],
            "asset_class": s.asset_class, "underlying": s.underlying, "instrument_key": ms.instrument_key,
            "strategy": s.strategy, "direction": s.direction, "regime": ms.regime,
            "defined_risk": 1 if s.defined_risk else 0,
            "regime_kind": s.regime_kind, "expiry": ms.expiry, "horizon_days": ms.days_to_expiry,
            "spot_entry": ms.spot, "atm_iv": ms.atm_iv, "realized_vol": ms.realized_vol_annual,
            "vrp_ratio": ms.vrp_ratio, "vrp_signal": ms.vrp_signal, "lot_size": ms.lot_size,
            "units": e["units"], "edge_prob": s.edge_prob, "calibrated_edge": None,
            "ev_gross": s.ev_gross, "ev_net": s.ev_net, "cost_rt": s.cost_round_trip,
            "max_loss": s.max_loss, "max_profit": s.max_profit, "net_credit": s.net_credit,
            "breakevens": json.dumps(s.breakevens), "legs": json.dumps(s.legs),
            "liquidity": s.liquidity, "status": e["status"], "action": e["action"],
            "gate_reasons": json.dumps(e["gate_reasons"]), "score": e["score"],
            "model_version": MODEL_VERSION, "provenance": "upstox_live", "lifecycle": "open",
        }
        cols = ",".join(row.keys())
        ph = ",".join(":" + k for k in row)
        before = con.total_changes
        con.execute(f"INSERT OR IGNORE INTO strat_tips ({cols}) VALUES ({ph})", row)
        n += (con.total_changes - before)
    con.commit()
    con.close()
    return n


# --- resolution -------------------------------------------------------------
def _intrinsic(ot: str, k: float, s_t: float) -> float:
    return max(s_t - k, 0.0) if ot == "CE" else max(k - s_t, 0.0)


def _pnl_per_lot(legs: list, lot: int, s_t: float) -> float:
    """Settlement P&L per lot at terminal spot (intrinsic — correct AT expiry)."""
    p = 0.0
    for lg in legs:
        intr = _intrinsic(lg["option_type"], lg["strike"], s_t)
        per = (lg["entry_fill"] - intr) if lg["side"] == "SELL" else (intr - lg["entry_fill"])
        p += per
    return p * lot


def _mtm_per_lot(legs: list, lot: int, fwd: float, iv: float, t_rem: float) -> float:
    """Interior mark-to-market per lot via Black-76 (intrinsic + TIME VALUE) — the true cost to
    close mid-life. Used for honest MAE/MFE and stop detection (adversary: intrinsic-only understates
    a short-seller's drawdown). Collapses to intrinsic as t_rem→0."""
    p = 0.0
    for lg in legs:
        val = engine_v2.black76_price(lg["option_type"], fwd, lg["strike"], t_rem, iv)
        per = (lg["entry_fill"] - val) if lg["side"] == "SELL" else (val - lg["entry_fill"])
        p += per
    return p * lot


def _settle_cost(legs: list, lot: int, units: int, s_t: float) -> float:
    # Held to expiry → settlement, not a closing trade: no close-side brokerage/slippage (#6).
    priced = [{**lg, "exit_fill": _intrinsic(lg["option_type"], lg["strike"], s_t)} for lg in legs]
    return costs_v2.round_trip_cost(priced, lot, units, settlement_exit=True)["total"]


def resolve_open(client, db_path: str | None = None, verbose: bool = True) -> dict:
    """Resolve open structures whose expiry close is now available. Uses daily candles only
    (post-horizon data → no look-ahead). MAE/MFE from the daily high/low path."""
    con = connect(db_path)
    rows = con.execute("SELECT * FROM strat_tips WHERE lifecycle='open' AND action='TRADE'").fetchall()
    resolved = 0
    cache = {}
    for r in rows:
        key = r["instrument_key"]
        try:
            if key not in cache:
                cache[key] = client.daily_candles(key, days=60)
            candles = cache[key]
        except Exception as ex:
            if verbose:
                print(f"  ! resolve fetch failed {r['underlying']}: {str(ex)[:80]}")
            continue
        exp = r["expiry"]
        # need a candle ON/AFTER expiry to settle
        after = [c for c in candles if c["ts"][:10] >= exp]
        if not after:
            continue  # not expired yet → stays open, counted, never assumed flat
        settle = after[0]
        terminal = settle["c"]
        legs = json.loads(r["legs"])
        lot, units = r["lot_size"], r["units"]
        iv = r["atm_iv"] or 0.0
        defined = bool(r["defined_risk"])
        exp_dt = datetime.fromisoformat(exp)

        # Path AFTER entry day → expiry. Strictly > entry date so the entry candle's pre-entry
        # intraday extremes can't leak in (adversary #4). Interior points marked at TRUE MTM
        # (Black-76, intrinsic+time value) so MAE/MFE and the stop are honest, not flattered.
        window = [c for c in candles if r["created_date"] < c["ts"][:10] <= exp]
        mae = mfe = 0.0
        stop_hit = 0
        stop_thresh = -abs(r["max_loss"]) * units      # modeled stop = position modeled max-loss
        for c in window:
            t_rem = max((exp_dt - datetime.fromisoformat(c["ts"][:10])).days, 0) / 365.0
            for px in (c["l"], c["h"]):
                pl = _mtm_per_lot(legs, lot, px, iv, t_rem) * units
                mae = min(mae, pl)
                mfe = max(mfe, pl)
                if pl <= stop_thresh:
                    stop_hit = 1
        pnl_close_gross = _pnl_per_lot(legs, lot, terminal) * units   # settlement = intrinsic (correct)
        cost = _settle_cost(legs, lot, units, terminal)
        pnl_close = pnl_close_gross - cost
        # Booking: defined-risk → respect the stop (loss bounded by the long wings). Naked → NEVER
        # clamp to the stress estimate; a >3σ gap fills worse than the stop, so book the WORSE of the
        # stop and the true settlement (adversary #2: don't truncate the gap tail).
        if stop_hit:
            pnl_stopped = (stop_thresh - cost) if defined else min(stop_thresh - cost, pnl_close)
        else:
            pnl_stopped = pnl_close
        pnl_final = pnl_stopped
        ret_on_risk = pnl_final / (abs(r["max_loss"]) * units) if (r["max_loss"] and units) else 0.0

        # VRP audit at resolution
        rv_window = _realized_vol_annual([c["c"] for c in window]) if len(window) >= 3 else None
        vrp_res = (rv_window / r["atm_iv"]) if (rv_window and r["atm_iv"]) else None

        con.execute("""INSERT OR REPLACE INTO strat_outcomes VALUES
            (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            r["tip_id"], settle["ts"], round(terminal, 2), round(pnl_close, 2),
            round(pnl_stopped, 2), round(pnl_final, 2), round(ret_on_risk, 4),
            1 if pnl_final > 0 else 0, 1 if pnl_close > 0 else 0, round(mae, 2), round(mfe, 2),
            stop_hit, round(vrp_res, 4) if vrp_res else None,
            round(rv_window, 4) if rv_window else None, f"settled@{exp}"))
        con.execute("UPDATE strat_tips SET lifecycle='resolved' WHERE tip_id=?", (r["tip_id"],))
        resolved += 1
    con.commit()
    con.close()
    if verbose:
        print(f"  resolved {resolved} structure(s)")
    return {"resolved": resolved}


def _realized_vol_annual(closes: list) -> float | None:
    rets = [(closes[i] / closes[i - 1] - 1.0) for i in range(1, len(closes)) if closes[i - 1]]
    if len(rets) < 2:
        return None
    m = sum(rets) / len(rets)
    var = sum((x - m) ** 2 for x in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(252.0)


# --- scorecard --------------------------------------------------------------
def _metrics(pnls: list, risks: list) -> dict:
    """Full honest metric block from per-trade net P&L (₹) and per-trade risk (₹)."""
    n = len(pnls)
    if n == 0:
        return {"n": 0}
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    total = sum(pnls)
    mean = total / n
    sd = math.sqrt(sum((p - mean) ** 2 for p in pnls) / (n - 1)) if n > 1 else 0.0
    downside = [p for p in pnls if p < 0]
    dsd = math.sqrt(sum(p * p for p in downside) / len(downside)) if downside else 0.0
    # equity curve + max drawdown (₹, additive on the notional book)
    eq, peak, max_dd = 0.0, 0.0, 0.0
    curve = []
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        max_dd = min(max_dd, eq - peak)
        curve.append(round(eq, 2))
    # CVaR 5% (mean of worst 5% trades)
    k = max(1, int(math.ceil(0.05 * n)))
    cvar = sum(sorted(pnls)[:k]) / k
    gross_profit = sum(wins)
    gross_loss = -sum(losses)
    ann = math.sqrt(252.0)  # rough: treat per-trade as ~daily for annualization
    sharpe = (mean / sd * ann) if sd > 0 else None
    sortino = (mean / dsd * ann) if dsd > 0 else None
    calmar = (total / abs(max_dd)) if max_dd < 0 else None
    return {
        "n": n,
        "win_rate": round(len(wins) / n, 4),
        "expectancy_inr": round(mean, 2),
        "expectancy_pct_of_risk": round(mean / (sum(risks) / len(risks)), 4) if risks and sum(risks) else None,
        "avg_win_inr": round(sum(wins) / len(wins), 2) if wins else None,
        "avg_loss_inr": round(sum(losses) / len(losses), 2) if losses else None,
        "total_pnl_inr": round(total, 2),
        "profit_factor": round(gross_profit / gross_loss, 3) if gross_loss > 0 else None,
        "std_inr": round(sd, 2),
        "sharpe": round(sharpe, 3) if sharpe is not None else None,
        "sortino": round(sortino, 3) if sortino is not None else None,
        # --- TAIL (mandatory, never hidden) ---
        "max_drawdown_inr": round(max_dd, 2),
        "worst_trade_inr": round(min(pnls), 2),
        "cvar_5pct_inr": round(cvar, 2),
        "calmar": round(calmar, 3) if calmar is not None else None,
        "equity_curve": curve,
    }


def report(client_unused=None, db_path: str | None = None) -> dict:
    con = connect(db_path)
    joined = con.execute("""SELECT t.*, o.pnl_final, o.pnl_close, o.pnl_stopped, o.win,
        o.profitable_close, o.mae, o.mfe, o.stop_hit, o.ret_on_risk, o.vrp_at_resolution,
        o.terminal_spot, o.resolved_ts
        FROM strat_tips t JOIN strat_outcomes o ON o.tip_id=t.tip_id
        WHERE t.action='TRADE' ORDER BY o.resolved_ts""").fetchall()
    open_n = con.execute("SELECT COUNT(*) FROM strat_tips WHERE lifecycle='open' AND action='TRADE'").fetchone()[0]
    total_tips = con.execute("SELECT COUNT(*) FROM strat_tips").fetchone()[0]
    abstained = con.execute("SELECT COUNT(*) FROM strat_tips WHERE action='NO_TRADE'").fetchone()[0]
    con.close()

    def block(rows):
        pnls = [r["pnl_final"] for r in rows]
        risks = [abs(r["max_loss"]) * r["units"] for r in rows]
        m = _metrics(pnls, risks)
        if rows:
            # close-vs-stop gap (how much the close-resolved number flatters us)
            close_total = sum(r["pnl_close"] for r in rows)
            stop_total = sum(r["pnl_stopped"] for r in rows)
            m["close_vs_stop_gap_inr"] = round(close_total - stop_total, 2)
            m["stop_hits"] = sum(r["stop_hit"] for r in rows)
            # stress exposure: any >2σ adverse day in the sample?
            m["stress_tested"] = any(r["stop_hit"] for r in rows) or (m.get("worst_trade_inr", 0) < -2 * (sum(risks) / len(risks)) if risks else False)
        return m

    by_class = {}
    for r in joined:
        by_class.setdefault(r["strategy"], []).append(r)
    strategy_breakdown = {k: block(v) for k, v in by_class.items()}

    by_regime = {}
    for r in joined:
        by_regime.setdefault(r["regime"], []).append(r)
    regime_breakdown = {k: block(v) for k, v in by_regime.items()}

    overall = block(joined)
    # edge verification per class (adversary #17: n>=sample AND positive expectancy)
    edge_status = {}
    for k, v in by_class.items():
        m = strategy_breakdown[k]
        verified = (m["n"] >= config.V2_EDGE_MIN_SAMPLE and (m.get("expectancy_inr") or -1) > config.V2_EDGE_MIN_EXPECTANCY)
        edge_status[k] = {
            "n": m["n"], "edge_verified": verified,
            "needs_n": config.V2_EDGE_MIN_SAMPLE,
            "message": (f"edge MEASURED: expectancy ₹{m.get('expectancy_inr')}/trade over {m['n']} trades"
                        if verified else
                        f"UNPROVEN: {m['n']}/{config.V2_EDGE_MIN_SAMPLE} resolved — WATCH only, not actionable"),
        }
    not_stress_tested = [k for k, m in strategy_breakdown.items() if not m.get("stress_tested")]

    return {
        "generated": datetime.now(_IST).isoformat(timespec="seconds"),
        "totals": {"tips_logged": total_tips, "resolved_trades": len(joined),
                   "open_trades": open_n, "abstained": abstained},
        "overall": overall,
        "by_strategy": strategy_breakdown,
        "by_regime": regime_breakdown,
        "edge_status": edge_status,
        "benchmark": {"do_nothing_cash_inr": 0.0,
                      "note": "Cash earns 0 here; 'edge' must be POSITIVE net P&L above this AND above the v1 directional baseline (see directional report)."},
        "tail_warning": ("CALM-REGIME ONLY — these classes have NOT survived a >2σ stress day; "
                         "do not read the win-rate/equity curve as proven edge: " + ", ".join(not_stress_tested)) if not_stress_tested else None,
        "disclaimer": config.V2_DISCLAIMER,
    }


def print_report(rep: dict) -> None:
    t = rep["totals"]
    print("\n================= ANVIL LIVE v2 — STRATEGY SCORECARD =================")
    print(f"tips logged={t['tips_logged']}  resolved={t['resolved_trades']}  "
          f"OPEN(still live, excluded from stats)={t['open_trades']}  abstained={t['abstained']}")
    o = rep["overall"]
    if o.get("n"):
        print(f"\n-- Overall (resolved structures, net of full India F&O costs) --")
        print(f"  n={o['n']}  win_rate={o['win_rate']}  expectancy=₹{o['expectancy_inr']}/trade  total=₹{o['total_pnl_inr']}")
        print(f"  TAIL: maxDD=₹{o['max_drawdown_inr']}  worst_trade=₹{o['worst_trade_inr']}  CVaR5%=₹{o['cvar_5pct_inr']}  "
              f"Sharpe={o['sharpe']}  Sortino={o['sortino']}  Calmar={o['calmar']}  PF={o['profit_factor']}")
        if o.get("close_vs_stop_gap_inr"):
            print(f"  close-vs-stop gap=₹{o['close_vs_stop_gap_inr']} (how much resolving at close flatters us; stop_hits={o.get('stop_hits')})")
    else:
        print("\n-- Overall: 0 resolved structures yet. Live edge accrues FORWARD as positions expire.")
        print("   (This is honest, not a failure: a fresh book has no track record. See the VRP backtest for the prior.)")
    for k, m in rep["by_strategy"].items():
        if m.get("n"):
            print(f"    {k:<24} n={m['n']:<4} win={m['win_rate']}  exp=₹{m['expectancy_inr']}  maxDD=₹{m['max_drawdown_inr']}  worst=₹{m['worst_trade_inr']}")
    if rep.get("tail_warning"):
        print("\n  ⚠ " + rep["tail_warning"])
    print("=====================================================================")
