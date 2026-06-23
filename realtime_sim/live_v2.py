"""Anvil Live v2 — orchestrator. The "run it against the market right now" entry point.

One cycle:
  1. Pull the LIVE Upstox feed for indices + stocks (chains with greeks/OI, daily candles).
  2. Build the analytics MarketState (VRP, GEX/regime, physical RND) per underlying.
  3. Build every option STRUCTURE, price its physical-measure EV/POP off real fills, gate + size it.
  4. Apply the portfolio short-vol stress cap; rank into ONE combined index+stock tip sheet.
  5. Log every idea (TRADE and ABSTAIN) to tips_v2.db; resolve any expired structures.
  6. Print the live regime read, the maximum-monetization tip sheet, the honest scorecard, and the
     real (non-circular) VRP backtest prior.

"Maximum monetization" = maximum expected calibrated edge per ₹ of risk, net of full India F&O
costs — expressed as ranked option structures, with abstention as a first-class output. Read-only;
no order is ever placed.

    python live_v2.py                 # full cycle: predict + log + resolve + scorecard + backtest
    python live_v2.py --no-resolve    # skip resolution
    python live_v2.py --backtest-only # just the VRP prior
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import backtest_v2
import config
import engine_v2
import gate_rank_v2
import structures_v2
import tracker_v2
from upstox_client import UpstoxClient

_IST = timezone(timedelta(hours=5, minutes=30))


def _verified_set(db_path=None) -> set:
    try:
        rep = tracker_v2.report(db_path=db_path)
        return {k for k, v in rep.get("edge_status", {}).items() if v.get("edge_verified")}
    except Exception:
        return set()


def _drawdown_halt(db_path=None) -> tuple[bool, float]:
    try:
        rep = tracker_v2.report(db_path=db_path)
        dd = rep["overall"].get("max_drawdown_inr", 0.0) or 0.0
        frac = abs(dd) / config.V2_CAPITAL
        return frac >= config.V2_DAILY_DRAWDOWN_KILL, frac
    except Exception:
        return False, 0.0


def build_states(client: UpstoxClient) -> dict:
    states = {}
    # indices (full chains)
    for name in config.V2_INDICES:
        try:
            ik = config.INDEX_INSTRUMENT_KEYS[name]
            chain = client.option_chain(name)
            candles = client.daily_candles(ik, days=120)
            ms = engine_v2.build_state(name, "index", chain, candles, ik)
            if ms:
                states[name] = ms
        except Exception as ex:
            print(f"  ! index {name} skipped: {type(ex).__name__}: {str(ex)[:110]}")
    # stocks (equity option chains — verified live)
    for sym in config.v2_stocks():
        try:
            ek = client.resolve_equity_key(sym)
            if not ek:
                print(f"  ! stock {sym}: no instrument key")
                continue
            chain = client.option_chain_by_key(ek, max_days=int(config.V2_MAX_DAYS_TO_EXPIRY))
            candles = client.daily_candles(ek, days=120)
            ms = engine_v2.build_state(sym, "stock", chain, candles, ek)
            if ms:
                states[sym] = ms
        except Exception as ex:
            print(f"  ! stock {sym} skipped: {type(ex).__name__}: {str(ex)[:110]}")
    return states


def run_cycle(do_resolve: bool = True) -> dict:
    client = UpstoxClient()
    halted, dd_frac = _drawdown_halt()
    verified = _verified_set()
    print("Anvil Live v2 — pulling live Upstox feed for %d indices + %d stocks..."
          % (len(config.V2_INDICES), len(config.v2_stocks())))

    states = build_states(client)
    if not states:
        print("No live market states could be built (market closed / token / connectivity?).")
        return {}

    # --- live regime / VRP / GEX snapshot ----------------------------------
    print("\n========== LIVE MARKET READ (regime · VRP · positioning) ==========")
    for name, ms in states.items():
        gtilt = "long-γ" if ms.net_gex >= 0 else "short-γ"
        pcr = f"{ms.pcr:.2f}" if ms.pcr is not None else "n/a"
        print(f"  {ms.asset_class:<5} {name:<11} spot={ms.spot:<10.2f} exp={ms.expiry} ({ms.days_to_expiry:.1f}d) "
              f"IV={ms.atm_iv*100:5.2f}% RV={ms.realized_vol_annual*100:5.2f}% "
              f"VRP={ms.vrp_ratio:.2f}[{ms.vrp_signal:<9}] {ms.regime:<31} GEX-tilt={gtilt:<7} PCR={pcr}")

    # --- build + gate + size every structure -------------------------------
    all_evals = []
    for name, ms in states.items():
        cands = structures_v2.build_candidates(ms)
        for s in cands:
            e = gate_rank_v2.evaluate(s, ms, config.V2_CAPITAL,
                                      lambda strat, reg, _v=verified: strat in _v)
            if halted and e["action"] == "TRADE":
                e["status"], e["action"], e["score"] = "ABSTAIN", "NO_TRADE", -1.0
                e["gate_reasons"] = e["gate_reasons"] + [f"drawdown kill-switch active ({dd_frac:.1%})"]
            all_evals.append(e)

    gate_rank_v2.apply_portfolio_cap(all_evals, config.V2_CAPITAL)
    ranked = gate_rank_v2.rank(all_evals)

    # --- the maximum-monetization tip sheet (combined index + stock) -------
    print("\n========== MAXIMUM-MONETIZATION TIP SHEET (ranked by net-EV per ₹ risk) ==========")
    if halted:
        print(f"  ⚠ DRAWDOWN KILL-SWITCH ACTIVE ({dd_frac:.1%} ≥ {config.V2_DAILY_DRAWDOWN_KILL:.0%}) — new trades suppressed.")
    n_act = sum(1 for e in ranked if e["status"] == "ACTIONABLE")
    print(f"  {len(ranked)} trade ideas | {n_act} ACTIONABLE (edge measured) | {len(ranked)-n_act} WATCH (edge UNPROVEN) "
          f"| {sum(1 for e in all_evals if e['action']=='NO_TRADE')} ABSTAIN")
    print(f"  {'#':<3}{'STATUS':<11}{'UNDERLYING':<12}{'STRATEGY':<24}{'POP':>6}{'EV/risk':>9}{'EVnet(pos)':>12}{'maxLoss(pos)':>14}{'units':>6}")
    for i, e in enumerate(ranked[:20], 1):
        s = e["structure"]
        print(f"  {i:<3}{e['status']:<11}{s.underlying:<12}{s.strategy:<24}{s.edge_prob*100:5.1f}%{s.ev_on_risk:>9.3f}"
              f"{e['ev_net_position']:>12,.0f}{e['max_loss_position']:>14,.0f}{e['units']:>6}")
    if ranked:
        print("\n  Top idea rationale: " + ranked[0]["structure"].rationale)
    else:
        print("  No structure cleared the gate this cycle — ABSTAIN is the call (no edge worth the risk now).")

    # --- log everything (TRADE + ABSTAIN) ----------------------------------
    created_ts = datetime.now(_IST).isoformat(timespec="seconds")
    n_logged = tracker_v2.log_evals(all_evals, states, created_ts=created_ts)
    print(f"\n  logged {n_logged} new ideas to {os.path.basename(config.V2_DB_PATH)} "
          f"(WATCH tips resolve at their option expiry → live track record accrues forward).")

    if do_resolve:
        print("\nResolving any expired structures...")
        tracker_v2.resolve_open(client)

    # --- scorecard (live track record so far) ------------------------------
    rep = tracker_v2.report()
    tracker_v2.print_report(rep)

    # --- save artifacts ----------------------------------------------------
    os.makedirs(config.REPORTS_DIR, exist_ok=True)
    stamp = datetime.now(_IST).strftime("%Y%m%d_%H%M%S")
    snapshot = {
        "generated": created_ts,
        "market_read": [{"underlying": ms.underlying, "asset_class": ms.asset_class, "spot": ms.spot,
                         "expiry": ms.expiry, "days_to_expiry": ms.days_to_expiry, "atm_iv": ms.atm_iv,
                         "realized_vol": ms.realized_vol_annual, "vrp_ratio": ms.vrp_ratio,
                         "vrp_signal": ms.vrp_signal, "regime": ms.regime, "net_gex": ms.net_gex,
                         "pcr": ms.pcr, "expected_move": ms.expected_move} for ms in states.values()],
        "tip_sheet": [{"rank": i + 1, "status": e["status"], "underlying": e["structure"].underlying,
                       "asset_class": e["structure"].asset_class, "strategy": e["structure"].strategy,
                       "direction": e["structure"].direction, "pop": e["structure"].edge_prob,
                       "ev_on_risk": e["structure"].ev_on_risk, "ev_net_position": e["ev_net_position"],
                       "max_loss_position": e["max_loss_position"], "units": e["units"],
                       "legs": e["structure"].legs, "breakevens": e["structure"].breakevens,
                       "rationale": e["structure"].rationale} for i, e in enumerate(ranked)],
        "scorecard": rep, "disclaimer": config.V2_DISCLAIMER,
    }
    path = os.path.join(config.REPORTS_DIR, f"live_v2_{stamp}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, default=str)
    print(f"\n  saved live snapshot → reports/{os.path.basename(path)}")
    return snapshot


def main(argv) -> int:
    if "--backtest-only" in argv:
        backtest_v2.print_backtest(backtest_v2.run_vrp_backtest())
        return 0
    run_cycle(do_resolve="--no-resolve" not in argv)
    # the honest 'how does the edge actually perform' evidence (real, non-circular)
    backtest_v2.print_backtest(backtest_v2.run_vrp_backtest())
    print("\n" + config.V2_DISCLAIMER)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
