"""Anvil CLI.

    python -m anvil.cli pull NIFTY --demo      # offline, no keys
    python -m anvil.cli pull NIFTY              # uses ANVIL_PRIMARY_SOURCE
    python -m anvil.cli mcp-check               # introspect the Kite MCP endpoint
    python -m anvil.cli serve                   # run the FastAPI app
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta

from .ingest import get_connector
from .ingest.demo import DemoConnector
from .pipeline import analyze_chain, to_snapshot


def _fmt(x, nd=0):
    if x is None:
        return "n/a"
    if isinstance(x, float):
        return f"{x:,.{nd}f}"
    return str(x)


def _print_summary(payload: dict) -> None:
    p = payload
    spot = p["spot"]
    line = "─" * 64
    print(line)
    print(f"  {p['underlying']}  spot {_fmt(spot, 1)}   expiry {p['expiry']}")
    print(line)

    oi = p["oi"]
    print("  OPEN INTEREST")
    print(f"    PCR(OI) {_fmt(oi['pcr_oi'],2)}   PCR(vol) {_fmt(oi['pcr_volume'],2)}   max-pain {_fmt(oi['max_pain'])}")
    cr = ", ".join(f"{int(k)}" for k, _ in oi["call_resistance"])
    ps = ", ".join(f"{int(k)}" for k, _ in oi["put_support"])
    print(f"    call resistance (OI): {cr}")
    print(f"    put support (OI):     {ps}")

    g = p["gex"]
    flip = g["zero_gamma_flip"]
    pos = "above" if (flip and spot >= flip) else "below"
    print("  DEALER POSITIONING (GEX)")
    print(f"    total GEX {_fmt(g['total_gex'])}   zero-gamma flip {_fmt(flip,1)}  (spot is {pos} flip)")

    d = p.get("implied_distribution")
    if d:
        print("  MARKET-IMPLIED DISTRIBUTION")
        em = d["expected_move_1sigma"]
        print(f"    ATM IV {(_fmt((d['atm_iv'] or 0)*100,1))}%   ±1σ move ≈ {_fmt(em,0)} pts "
              f"[{_fmt(spot-em,0)} – {_fmt(spot+em,0)}]")
        print(f"    P(close above spot by expiry) ≈ {_fmt((d['prob_above_spot'] or 0)*100,0)}%")

    r = p["regime"]
    print("  REGIME READ")
    print(f"    {r['label']}")
    for drv in r["drivers"]:
        print(f"      • {drv}")

    if "portfolio" in p:
        pf = p["portfolio"]
        print("  PORTFOLIO (beta-weighted to %s)" % pf["benchmark"])
        print(f"    net δ {_fmt(pf['net_delta'],1)}  γ {_fmt(pf['net_gamma'],3)}  "
              f"θ/day {_fmt(pf['net_theta'],0)}  vega/1% {_fmt(pf['net_vega'],0)}")
        print(f"    beta-weighted delta {_fmt(pf['beta_weighted_delta'],1)}  "
              f"({_fmt(pf['bwd_lots'],2)} {pf['benchmark']} lots)")
    print(line)
    print("  Analytics & education only — not investment advice.")
    print(line)


def cmd_pull(args) -> int:
    conn = DemoConnector() if args.demo else get_connector(args.source)
    chain = conn.get_chain(args.underlying, args.expiry)
    positions = conn.get_positions() if conn.provides_positions else None
    payload = analyze_chain(chain, positions)

    if args.json:
        print(json.dumps(payload, indent=2, default=str))
    else:
        _print_summary(payload)

    if args.store:
        from .store import SnapshotStore

        store = SnapshotStore()
        store.write(to_snapshot(payload), payload, source=conn.name, chain=chain)
        print(f"  snapshot stored → {store.path} (total for {args.underlying.upper()}: "
              f"{store.count(args.underlying.upper())})")
        store.close()
    return 0


def cmd_mcp_check(args) -> int:
    from .ingest.kite import introspect_mcp

    res = introspect_mcp(args.url, args.token)
    print(json.dumps(res, indent=2, default=str))
    return 0


def cmd_serve(args) -> int:
    import uvicorn

    uvicorn.run("anvil.api.app:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def cmd_cert(args) -> int:
    """Full-depth certification (Wave 5): parallel streaming index backtest (+ optional equities) across
    the bhavcopy cache → write cells to the TipValidationStore → report the gate verdict. This is what
    flips ``gate0_passed`` HONESTLY by raising independent-day n; spurious cells still fail the battery."""
    from pathlib import Path

    from .backtest.full_cert import run_full_cert
    from .ledger.ledger import CalibrationLedger
    from .tips.store import IssuedTipStore, TipValidationStore

    if args.action != "full":
        print(f"unknown cert action {args.action}")
        return 2
    cache = Path(args.cache_dir)
    if not cache.exists():
        print(f"cache dir {cache} not found — run: anvil data backfill --years 2")
        return 2
    start = date.fromisoformat(args.start) if args.start else None
    end = date.fromisoformat(args.end) if args.end else None
    unds = [u.strip().upper() for u in args.underlyings.split(",") if u.strip()]
    led = CalibrationLedger(args.ledger_path) if args.ledger_path else CalibrationLedger()
    store = TipValidationStore(args.store_path) if args.store_path else TipValidationStore()
    istore = IssuedTipStore(args.store_path) if args.store_path else IssuedTipStore()
    n_trials = 0
    if args.trials:
        from .backtest.trials import TrialRegistry
        reg = TrialRegistry()
        n_trials = reg.bump(f"cert:{args.underlyings.upper()}", int(args.trials))
        reg.close()
        print(f"trial registry: +{args.trials} → {n_trials} configs counted")
    print(f"cert full: underlyings={unds} window={start}..{end} workers={args.workers} "
          f"equities={args.equities} max_expiries={args.max_expiries}")
    try:
        res = run_full_cert(
            str(cache), unds, led, store, start=start, end=end, workers=args.workers,
            equities=args.equities, universe_size=args.universe_size, max_expiries=args.max_expiries,
            n_trials=(n_trials or None), issued_store=istore)
        idx = res["index"]
        print(f"  INDEX: issued {idx['recorded']}  resolved {idx['resolved']}  cells {idx['cells']}  "
              f"headline-eligible {idx['headline_cells']}  PBO {idx['global_pbo']}")
        for r in sorted(idx["reports"], key=lambda x: -x["n"])[:15]:
            flag = "HEADLINE" if r["headline_eligible"] else "watch"
            print(f"    {r['structure']:<16} {r['regime_bucket']:<13} n={r['n']:<4} "
                  f"win={r['win_rate']}  edge={r['cost_adjusted_edge']}  t={r['t_stat']}  "
                  f"dsr={r['dsr']}  [{flag}]")
        if args.equities and "equity" in res:
            e = res["equity"]
            print(f"  EQUITY: cells {e['cells']}  headline-eligible {e['headline_cells']}")
        print(f"  TOTAL headline-eligible cells: {res['headline_cells']}  "
              f"(gate0 {'PASSES' if res['headline_cells'] > 0 else 'does not pass yet'})")
    finally:
        led.close()
        store.close()
        istore.close()
    return 0


def _go_live_prep() -> None:
    """Best-effort one-command startup prep: report the live/demo source, ensure the instrument master is
    loaded (fetch on first run), and refresh stale index closes for momentum. EVERY step is guarded — prep
    never blocks or crashes the server start; a failed step just degrades that feature, not the cockpit."""
    print("preparing live cockpit…")
    try:
        from .ingest.source import pick_connector

        _conn, status = pick_connector()
        if status.mode == "live":
            print(f"  + live source: {status.resolved}")
        else:
            print("  ! DEMO data (no live broker token). For live: run `anvil auth upstox`, then restart.")
    except Exception as e:  # noqa: BLE001
        print(f"  ! source check failed: {str(e)[:120]}")
    try:
        from .ingest.instruments import (
            fetch_and_cache_instruments,
            get_master,
            load_cached_instruments,
        )

        if not get_master().key_by_symbol and load_cached_instruments() is None:
            print("  … fetching Upstox instrument master (first run)…")
            r = fetch_and_cache_instruments()
            print(f"  + instruments: spot_keys={r.get('spot_keys')}" if r.get("ok")
                  else f"  ! instruments fetch failed: {r.get('error')}")
        else:
            print("  + instrument master loaded")
    except Exception as e:  # noqa: BLE001
        print(f"  ! instruments prep failed: {str(e)[:120]}")
    try:
        import time

        from .ingest import yahoo

        p = yahoo.cache_path("^NSEI")
        stale = (not p.exists()) or (time.time() - p.stat().st_mtime > 18 * 3600)
        if stale:
            print("  … refreshing index closes (momentum history)…")
            for sym in ("^NSEI", "^NSEBANK", "^INDIAVIX"):
                yahoo.fetch_and_cache(sym)
            print("  + index closes refreshed")
        else:
            print("  + index closes fresh")
    except Exception as e:  # noqa: BLE001
        print(f"  ! closes prep failed: {str(e)[:120]}")


def cmd_go_live(args) -> int:
    """One-process live cockpit (Wave 0): the REST API + the LiveSupervisor (always-on recorder +
    per-tick cockpit predictions/momentum + the nightly moat clock) in a single process, so the PWA
    updates live. Auto-preps (token check + instruments + closes) so it's a ONE-command launch; reuses
    the same functions as the standalone CLI jobs — no fork."""
    import uvicorn

    from .config import SETTINGS

    # SETTINGS is a FROZEN dataclass singleton; go-live runs uvicorn in THIS process (reload=False), so
    # set the runtime overrides on the singleton via object.__setattr__ — the app lifespan reads them.
    object.__setattr__(SETTINGS, "live_supervisor_enabled", True)
    if args.force_open:
        object.__setattr__(SETTINGS, "cockpit_force_open", True)
    if args.underlyings:
        object.__setattr__(SETTINGS, "cockpit_underlyings", args.underlyings)
    if not args.no_prep:
        _go_live_prep()
    print(f"go-live: API http://{args.host}:{args.port}  +  supervisor "
          f"(underlyings={SETTINGS.cockpit_underlyings}, force_open={SETTINGS.cockpit_force_open})")
    print("  open the PWA; the header shows DEMO/LIVE + freshness; Ctrl-C cancels all tasks cleanly.")
    # reload MUST stay off: a reloader subprocess re-imports config and loses these in-process flags.
    uvicorn.run("anvil.api.app:app", host=args.host, port=args.port, reload=False)
    return 0


def cmd_data(args) -> int:
    """Lightweight pandas-free data fetch (Yahoo chart JSON): daily OHLC + India VIX, cached for the
    decision-brief's realized-vol/regime history and honest touch resolution (daily high/low)."""
    from .ingest import yahoo

    if args.action == "fetch-closes":
        syms = [s.strip() for s in (args.symbols or "^NSEI,^NSEBANK,^INDIAVIX").split(",") if s.strip()]
        for sym in syms:
            res = yahoo.fetch_and_cache(sym, range_=args.range)
            bars = res.get("bars", [])
            note = " (from cache)" if res.get("from_cache") else ""
            span = f"{bars[0]['date']}…{bars[-1]['date']}" if bars else "—"
            print(f"  {sym:<12} bars={len(bars):<5} span={span} skipped={res.get('skipped', 0)}{note}")
            if res.get("error"):
                print(f"    ! {res['error']}")
        return 0

    if args.action == "backfill":
        from datetime import datetime, timedelta

        from .ingest.backfill import backfill_bhavcopy
        from .live.clock import IST

        if args.years is not None:
            end = datetime.now(IST).date()
            start = end - timedelta(days=int(round(args.years * 365.25)))
        elif args.start and args.end:
            start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
        else:
            print("backfill needs --years N, or both --start and --end (ISO dates)")
            return 2
        from pathlib import Path as _Path

        log_path = args.log or str(_Path(args.cache_dir) / "backfill.log")
        print(f"backfill NSE F&O bhavcopy {start}…{end} → {args.cache_dir} (workers={args.workers}) "
              f"· checkpoint log → {log_path}")
        res = backfill_bhavcopy(start, end, args.cache_dir, workers=args.workers, log_path=log_path,
                                progress=lambda d, st, _x: print(f"  {st:<8} {d.isoformat()}"))
        print(f"done: {res['trading_days']} trading days · {res['already_cached']} already cached · "
              f"{res['fetched']} fetched · {len(res['failed'])} missing")
        if res["missing"]:
            print(f"  missing (report, not hidden): {', '.join(res['missing'][:30])}"
                  + (" …" if len(res["missing"]) > 30 else ""))
        return 0

    if args.action == "health":
        from .backtest.health import data_health_report, render_health

        report = data_health_report(cache_dir=args.cache_dir)
        print(render_health(report))
        return 0 if report["ok"] else 1

    if args.action == "fetch-positioning":
        from .ingest.positioning import fetch_and_cache_positioning

        res = fetch_and_cache_positioning(date_iso=args.date)
        print(f"positioning {res['date']}: participants={res['participants']} vix={res['vix']} "
              f"→ {res['path']}{'  (error: ' + res['error'] + ')' if res.get('error') else ''}")
        return 0 if not res.get("error") else 1

    if args.action == "fetch-instruments":
        from .ingest.instruments import fetch_and_cache_instruments

        res = fetch_and_cache_instruments()
        if res.get("ok"):
            print(f"instruments: {res['instruments']} rows · spot_keys={res['spot_keys']} · "
                  f"option_underlyings={res['option_underlyings']} → {res['path']}")
            return 0
        print(f"instruments fetch failed: {res.get('error')} (from_cache={res.get('from_cache')}, "
              f"spot_keys={res.get('spot_keys')})")
        return 1

    if args.action == "fetch-candles":
        from .ingest import get_connector
        from .ingest.candle_cache import fetch_candles
        from .ingest.instruments import get_master, load_cached_instruments
        from .ingest.source import pick_connector

        conn = get_connector(args.source) if args.source else pick_connector()[0]
        if not get_master().key_by_symbol:
            load_cached_instruments()  # enable equity candle keys if a dump was cached
        tfs = [t.strip() for t in (args.tf or "1d,1h,15m,5m,1m").split(",") if t.strip()]
        unds = [u.strip().upper() for u in (args.underlyings or "NIFTY,BANKNIFTY").split(",") if u.strip()]
        print(f"fetch-candles: underlyings={unds} tfs={tfs} src={getattr(conn, 'name', args.source)} "
              f"intraday={args.intraday}")
        rc = 0
        for u in unds:
            res = fetch_candles(conn, u, tfs, intraday=args.intraday)
            stored = " ".join(f"{tf}={res['stored'].get(tf, 0)}" for tf in tfs)
            print(f"  {u:<12} written={sum(res['by_tf'].values()):<5} stored[{stored}]")
            if res["errors"]:
                rc = 1
                for tf, msg in res["errors"].items():
                    print(f"    ! {tf}: {msg}")
        return rc

    if args.action == "build-bars":
        from .live.bar_aggregator import build_bars_from_snapshots

        tfs = [t.strip() for t in (args.tf or "1m,5m,1h").split(",") if t.strip()]
        unds = [u.strip().upper() for u in (args.underlyings or "NIFTY,BANKNIFTY").split(",") if u.strip()]
        print(f"build-bars from recorded spot ticks: underlyings={unds} tfs={tfs}")
        for u in unds:
            res = build_bars_from_snapshots(u, tfs)
            by_tf = " ".join(f"{tf}={res['by_tf'].get(tf, 0)}" for tf in tfs)
            print(f"  {u:<12} ticks={res['ticks']:<6} bars[{by_tf}]")
        return 0

    print(f"unknown data action {args.action}")
    return 2


def cmd_record(args) -> int:
    """Always-on intraday option-chain recorder (IST market hours). Designed to run under Windows Task
    Scheduler 09:10–15:35 IST; captures the unbuyable per-strike OI/IV history into the snapshot store."""
    from .live.recorder_loop import run_recorder

    unds = [u.strip().upper() for u in (args.underlyings or "NIFTY").split(",") if u.strip()]
    print(f"recorder start: underlyings={unds} cadence={args.cadence}s source={args.source or 'auto-live'} "
          f"once={args.once} force_open={args.force_open}")
    res = run_recorder(unds, cadence_s=args.cadence, source=args.source, once=args.once,
                       force_open=args.force_open, max_ticks=args.max_ticks)
    print(f"recorder done: status={res['status']} ticks={res['ticks']} recorded={res['recorded']} "
          f"errors={res['errors']} last={res.get('last_ts')}")
    return 0 if res["status"] in ("ok", "closed") else 1


def cmd_decision_brief(args) -> int:
    """Compute (and optionally RECORD for calibration) the buyer Decision Brief for an underlying."""
    from .engine.decision_brief import decision_brief
    from .ingest import get_connector, yahoo
    from .ingest.base import attach_parity_forward
    from .strategy.context import SignalContext

    conn = get_connector(args.source) if args.source else get_connector()
    chain = attach_parity_forward(conn.get_chain(args.underlying))
    ctx = SignalContext(chain, source=conn.name)
    history = yahoo.history_for(args.underlying, range_=args.range)
    brief = decision_brief(ctx, history_ohlc=yahoo.ohlc_tuples(history), horizon_days=args.horizon)
    env = brief.environment
    vrp = env["vrp"]
    reg = env["regime"]
    print(f"DECISION BRIEF — {brief.underlying} @ {brief.spot}  (horizon {brief.horizon_days}d, "
          f"source={conn.name}, history={len(history)}d)")
    print(f"  ENVIRONMENT: {brief.verdict}")
    if brief.flip_condition:
        print(f"    flip → {brief.flip_condition}")
    print(f"    VRP: {vrp.get('richness')}  P(realized<implied)={vrp.get('prob_realized_lt_implied')}  "
          f"IV={vrp.get('atm_iv')} E[RV]={vrp.get('e_rv')} ({env['rv_forecast'].get('method')})")
    print(f"    Regime: {reg['label']}  ({reg['agree_count']}/{reg['signals_total']} signals agree)")
    print(f"    Term: {env['term_structure'].get('shape')}  Crush: {env['crush_window'].get('reason')}")
    print(f"  STRIKE-ACTION (P(touch) within {brief.horizon_days}d, VRP-adjusted{' — MUTED' if env['verdict'] in ('UNFAVORABLE','ABSTAIN') else ''}):")
    for s in brief.strikes:
        print(f"    {s['strike']:>10.0f} {s['dir']:<4} ({s['distance_pct']:+.1f}%)  "
              f"P(touch)={s['p_touch_phys']:.2f}  [rn {s['p_touch_rn']:.2f}]")

    if args.record:
        from .ledger.ledger import CalibrationLedger, emit_structural_forecasts

        touch_probs = {s["strike"]: {"p_touch_phys": s["p_touch_phys"], "dir": s["dir"]}
                       for s in brief.strikes}
        src = "demo" if conn.name in ("demo", "seed") else "struct_live"
        resolve_ts = chain.expiry  # horizon-end resolution handled by a later cycle
        led = CalibrationLedger(args.ledger_path) if args.ledger_path else CalibrationLedger()
        try:
            fcs = emit_structural_forecasts(chain, touch_probs, vrp, brief.horizon_days,
                                            resolve_ts=resolve_ts, source=src)
            n = led.record_many(fcs)
            print(f"  recorded {n} structural forecasts (source={src}) for calibration accrual.")
        finally:
            led.close()
    return 0


def _seed_ledger(led, n: int) -> int:
    """Backfill a synthetic, well-calibrated resolved history so the reliability curve is
    demonstrable. Clearly tagged source='seed' — NOT real forecasts."""
    from .ledger.ledger import KIND_PROB_ABOVE, Forecast

    per = max(n // 10, 1)
    seq = 0
    for b in range(10):
        p = (b + 0.5) / 10.0
        ones = round(p * per)
        for j in range(per):
            event = 1 if j < ones else 0
            f = Forecast(
                underlying="SEED", created_ts="2026-01-01T00:00:00+00:00",
                resolve_ts="2026-01-08", kind=KIND_PROB_ABOVE,
                params={"level": 100.0, "seq": seq}, prob=p, spot=100.0, forward=100.0,
                source="seed",
            )
            led.record(f)
            led.resolve(f.id, realized_value=101.0 if event else 99.0)
            seq += 1
    return seq


def _bar(frac: float, width: int = 20) -> str:
    n = max(0, min(width, round((frac or 0) * width)))
    return "█" * n + "·" * (width - n)


def _print_ledger_panel(title: str, m: dict) -> None:
    cs = m.get("calibration_score") or {}
    score = cs.get("score")
    score_str = f"{score}/100 ({cs.get('rating')})" if score is not None else cs.get("rating", "—")
    print(f"  {title.upper()} — Calibration Score: {score_str}")
    print(f"    resolved {m['resolved_count']}   pending {m['pending_count']}")
    if m["brier"] is not None:
        print(f"    Brier {m['brier']:.4f}   log-loss {m['log_loss']:.4f}   ECE {m['ece']:.4f}")
    cov = m["band_coverage"]
    if cov["count"]:
        print(f"    band coverage: nominal {cov['nominal']*100:.0f}%  realized {cov['realized']*100:.0f}%  (n={cov['count']})")
    if m["reliability_curve"]:
        print(f"    {'predicted':>9}  {'empirical':>9}  {'n':>5}   diagonal = calibrated")
        for r in m["reliability_curve"]:
            print(f"    {r['predicted_mean']*100:8.0f}%  {r['empirical_freq']*100:8.0f}%  {r['count']:5d}   {_bar(r['empirical_freq'])}")
    else:
        print("    (no resolved forecasts yet)")


def _print_ledger_report(by_class: dict) -> None:
    line = "─" * 64
    print(line)
    print("  CALIBRATION LEDGER — real track record only (synthetic excluded)")
    print(line)
    _print_ledger_panel("Backtested · real EOD (out-of-sample)", by_class["backtest"])
    print("")
    _print_ledger_panel("Live · forward forecasts", by_class["live"])
    excluded = by_class["backtest"].get("counts_by_class", {})
    synth = excluded.get("seed", 0) + excluded.get("demo", 0)
    if synth:
        print(f"\n  ({synth} synthetic/demo forecasts in the DB are excluded from the curves above.)")
    print(line)
    print("  Analytics & education only — not investment advice.")
    print(line)


def cmd_auth(args) -> int:
    from .auth.token_store import TokenStore

    store = TokenStore()
    if args.provider == "upstox":
        from .auth import upstox_auth

        token = upstox_auth.login(store)
        print(f"✅ Upstox authenticated; token cached (valid until {store.load('upstox')['expires_at']}).")
        print(f"   token: {token[:8]}…")
    elif args.provider == "kite":
        from .auth import kite_auth

        rt = args.request_token
        if not rt:
            print("1) Open this URL, log in, and copy the request_token from the redirect:")
            print("   " + kite_auth.login_url(args.api_key or "<KITE_API_KEY>"))
            rt = input("request_token> ").strip()
        kite_auth.login(rt, store)
        print(f"✅ Kite authenticated; token cached (valid until {store.load('kite')['expires_at']}).")
    elif args.provider == "groww":
        from .config import SETTINGS

        try:
            from growwapi import GrowwAPI
        except ImportError:
            print("growwapi not installed — `pip install \".[brokers]\"` (Python ≤3.13 / 3.12 container).")
            return 2
        if SETTINGS.groww_totp_seed and SETTINGS.groww_api_key:
            import pyotp

            token = GrowwAPI.get_access_token(
                api_key=SETTINGS.groww_api_key, totp=pyotp.TOTP(SETTINGS.groww_totp_seed).now()
            )
        elif SETTINGS.groww_api_key and SETTINGS.groww_api_secret:
            token = GrowwAPI.get_access_token(
                api_key=SETTINGS.groww_api_key, secret=SETTINGS.groww_api_secret
            )
        else:
            print("Set GROWW_API_KEY + (GROWW_TOTP_SEED or GROWW_API_SECRET).")
            return 2
        store.save("groww", token)
        print("✅ Groww authenticated; token cached.")
    elif args.provider == "status":
        for broker in ("upstox", "kite", "groww"):
            blob = store.load(broker)
            if not blob:
                print(f"  {broker:8} — no token")
            else:
                ok = "valid" if store.is_valid(broker) else "EXPIRED"
                print(f"  {broker:8} — {ok} (expires {blob.get('expires_at')})")
    return 0


def cmd_order(args) -> int:
    from .execution.gateway import AssistedExecutor, OrderRequest
    from .execution.groww_gateway import GrowwOrderGateway

    gw = GrowwOrderGateway(dry_run=not args.live)
    ex = AssistedExecutor(gateway=gw)
    req = OrderRequest(
        symbol=args.symbol, side=args.side.upper(), quantity=args.qty,
        order_type=args.type.upper(), price=args.price, product=args.product.upper(),
        exchange=args.exchange.upper(), segment=args.segment.upper(), rationale=args.rationale or "",
    )
    mode = "LIVE" if args.live else "DRY-RUN"
    ticket = ex.propose(req)
    print(f"PROPOSED [{mode}]: {req.side} {req.quantity} {req.symbol} {req.order_type}"
          + (f" @ {req.price}" if req.price else "") + f"  ({req.segment}/{req.product})")
    confirm = "y" if args.yes else input("Confirm this order? [y/N] ").strip().lower()
    if confirm != "y":
        print("cancelled — no order sent.")
        return 0
    placed = ex.confirm(ticket)
    msg = f"{placed.status}: {placed.note}"
    if placed.broker_order_id:
        msg += f"  order_id={placed.broker_order_id}"
    print(msg)
    return 0


def cmd_ledger(args) -> int:
    from .engine.implied_dist import implied_distribution
    from .ledger.ledger import CalibrationLedger, emit_forecasts

    led = CalibrationLedger()
    try:
        if args.action == "record":
            conn = DemoConnector() if args.demo else get_connector(args.source)
            chain = conn.get_chain(args.underlying, args.expiry)
            dist = implied_distribution(chain)
            # Tag with the connector name so the source-class rail can keep demo data out of
            # the public reliability curve (demo→"demo" excluded; upstox/groww/…→"live").
            fs = emit_forecasts(chain, dist, source=conn.name)
            led.record_many(fs)
            klass = "demo (excluded from public curve)" if conn.name == "demo" else "live"
            print(f"recorded {len(fs)} {klass} forecasts for {chain.underlying} "
                  f"(resolve {chain.expiry})")
        elif args.action == "resolve":
            if args.realized is None:
                print("--realized <index level> is required for resolve")
                return 2
            n = led.resolve_due(args.underlying, args.realized, args.as_of)
            print(f"resolved {n} due forecasts for {args.underlying} at realized {args.realized}")
        elif args.action == "seed":
            n = _seed_ledger(led, args.n)
            print(f"seeded {n} synthetic resolved forecasts (source=seed — EXCLUDED from the "
                  "public reliability curve; QA/illustration only)")
        elif args.action == "run-daily":
            conn = DemoConnector() if args.demo else get_connector(args.source)
            unds = [u.strip().upper() for u in (args.underlying or "NIFTY").split(",")]
            realized = (
                {unds[0]: args.realized}
                if (args.realized is not None and len(unds) == 1)
                else None
            )
            if args.full:
                # The full "moat clock": snapshot + forecasts + resolve + issue/resolve tips +
                # revalidate the gate from accrued live evidence (schedule this ~16:00 IST).
                from .live.cycle import run_daily_cycle

                # The moat clock auto-resolves (Phase 5) when no realized close was hand-fed, so the
                # scheduled `ledger run-daily --full` accrues a live track record on its own.
                res = run_daily_cycle(unds, connector=conn, ledger=led, realized=realized,
                                      as_of=args.as_of, auto_resolve=(realized is None))
                rec, rsv = res.get("recorded"), res.get("resolved")
                rec_n = sum(rec.values()) if isinstance(rec, dict) else rec
                rsv_n = sum(rsv.values()) if isinstance(rsv, dict) else rsv
                tips = res.get("tips") or {}
                t_iss, t_rsv = tips.get("issued", 0), tips.get("resolved", 0)
                t_rsv = sum(t_rsv.values()) if isinstance(t_rsv, dict) else t_rsv
                print(f"daily-cycle [{res.get('source', conn.name)}]: forecasts {rec_n}  "
                      f"resolved {rsv_n}  snapshots {len(res.get('snapshots', {}))}  "
                      f"tips issued {t_iss}/resolved {t_rsv}")
            else:
                from .live.daily import run_daily

                res = run_daily(unds, connector=conn, ledger=led, realized=realized, as_of=args.as_of,
                                auto_resolve=(realized is None))
                print(f"live run [{conn.name}]: recorded {res['recorded']}  resolved {res['resolved']}")
        elif args.action == "report":
            _print_ledger_report(led.metrics_by_class())
    finally:
        led.close()
    return 0


def cmd_backtest(args) -> int:
    from .backtest import BhavcopyArchive, run_backtest
    from .ingest.bhavcopy import fetch_bhavcopy_text
    from .ledger.ledger import CalibrationLedger

    from pathlib import Path

    cache = Path(args.cache_dir)
    unds = [u.strip().upper() for u in args.underlyings.split(",")]
    start = date.fromisoformat(args.start) if args.start else None
    end = date.fromisoformat(args.end) if args.end else None

    if args.action == "fetch":
        cache.mkdir(parents=True, exist_ok=True)
        if not (start and end):
            print("fetch needs --start and --end (ISO dates)")
            return 2
        got = 0
        d = start
        while d <= end:
            if d.weekday() < 5:  # skip weekends; holidays handled by the error path
                try:
                    (cache / f"fo_{d.isoformat()}.csv").write_text(
                        fetch_bhavcopy_text(d), encoding="utf-8"
                    )
                    got += 1
                    print(f"  fetched {d.isoformat()}")
                except Exception as e:  # noqa: BLE001 - best-effort, NSE is fragile
                    print(f"  skip {d.isoformat()}: {e}")
            d += timedelta(days=1)
        print(f"cached {got} bhavcopy files → {cache}")
        return 0

    # action == "run"
    if not cache.exists():
        print(f"cache dir {cache} not found — run: anvil backtest fetch --start … --end …")
        return 2
    arch = BhavcopyArchive.from_cache_dir(cache)
    led = CalibrationLedger()
    try:
        res = run_backtest(arch, unds, led, start=start, end=end)
        days = len(arch.trading_days(start, end))
        print(f"backtest [{','.join(unds)}]: recorded {res['recorded']}  resolved "
              f"{res['resolved']} forecasts over {days} trading days")
        _print_ledger_report(led.metrics_by_class())
    finally:
        led.close()
    return 0


def cmd_tips(args) -> int:
    from pathlib import Path

    from .backtest import BhavcopyArchive
    from .backtest.tip_backtest import run_tip_backtest
    from .ledger.ledger import CalibrationLedger
    from .tips.store import TipValidationStore

    if args.action == "backtest":
        cache = Path(args.cache_dir)
        if not cache.exists():
            print(f"cache dir {cache} not found — run: anvil backtest fetch --start … --end …")
            return 2
        start = date.fromisoformat(args.start) if args.start else None
        end = date.fromisoformat(args.end) if args.end else None
        led = CalibrationLedger(args.ledger_path) if args.ledger_path else CalibrationLedger()
        store = TipValidationStore(args.store_path) if args.store_path else TipValidationStore()
        # Honest multiple-testing count: when the operator declares a sweep (--trials N), log it to the
        # persisted registry and feed the running total to the Deflated Sharpe so the bar rises.
        n_trials = 0
        if args.trials:
            from .backtest.trials import TrialRegistry
            reg = TrialRegistry()
            scope = "equities" if args.equities else f"options:{args.underlyings.upper()}"
            n_trials = reg.bump(scope, int(args.trials))
            reg.close()
            print(f"trial registry [{scope}]: +{args.trials} → {n_trials} configs counted")
        try:
            if args.equities:
                from .tips.equities import EQUITY_POOL, discover_universe, run_equity_backtest

                uni = discover_universe(cache, top_n=args.universe_size)
                arch = BhavcopyArchive.from_cache_dir(cache, universe=set(uni))
                res = run_equity_backtest(arch, uni, led, store, start=start, end=end,
                                          min_samples=args.min_samples, top_k=args.top_k, n_trials=n_trials)
                p = res.get("pooled") or {}
                print(f"equity tip-backtest [{len(uni)} stocks]: issued {res['recorded']}  resolved "
                      f"{res['resolved']}  cells {res['cells']}  headline-eligible {res['headline_cells']}")
                print(f"  POOLED {EQUITY_POOL}: n={p.get('n')} win={p.get('win_rate')} "
                      f"conv={p.get('mean_conviction')} edge={p.get('cost_adjusted_edge')} "
                      f"t={p.get('t_stat')} dsr={p.get('dsr')} pbo={p.get('pbo')} "
                      f"headline={p.get('headline_eligible')}")
            else:
                unds = [u.strip().upper() for u in args.underlyings.split(",")]
                arch = BhavcopyArchive.from_cache_dir(cache)
                res = run_tip_backtest(arch, unds, led, store, start=start, end=end,
                                       min_samples=args.min_samples, max_expiries=args.max_expiries,
                                       n_trials=n_trials)
                print(f"tip-backtest [{','.join(unds)}]: issued {res['recorded']}  resolved "
                      f"{res['resolved']}  cells {res['cells']}  headline-eligible "
                      f"{res['headline_cells']}  PBO {res['global_pbo']}")
                for r in sorted(res["reports"], key=lambda x: -x["n"])[:20]:
                    flag = "HEADLINE" if r["headline_eligible"] else "watch"
                    print(f"  {r['structure']:<18} {r['regime_bucket']:<14} n={r['n']:<4} "
                          f"win={r['win_rate']}  edge={r['cost_adjusted_edge']}  t={r['t_stat']}  "
                          f"dsr={r['dsr']}  [{flag}]")
        finally:
            led.close()
            store.close()
        return 0

    if args.action == "run-eod":
        from .tips.store import IssuedTipStore

        led = CalibrationLedger(args.ledger_path) if args.ledger_path else CalibrationLedger()
        vstore = TipValidationStore(args.store_path) if args.store_path else TipValidationStore()
        istore = IssuedTipStore(args.store_path) if args.store_path else IssuedTipStore()
        try:
            if args.equities:
                from .tips.equities import discover_universe, run_equity_tip_cycle

                cache = Path(args.cache_dir)
                uni = discover_universe(cache, top_n=args.universe_size)
                arch = BhavcopyArchive.from_cache_dir(cache, universe=set(uni))
                as_of = date.fromisoformat(args.as_of) if args.as_of else arch.trading_days()[-1]
                res = run_equity_tip_cycle(arch, as_of=as_of, ledger=led, validation_store=vstore,
                                           issued_store=istore, top_k=args.top_k)
                print(f"tips run-eod [equities] {as_of.isoformat()}: issued {res['issued']}  "
                      f"buys {res['buys']}  sells {res['sells']}  resolved {res['resolved']}")
            else:
                from .tips.eod import run_tip_cycle

                unds = [u.strip().upper() for u in args.underlyings.split(",")]
                realized = {unds[0]: args.realized} if (args.realized is not None and unds) else None
                res = run_tip_cycle(unds, ledger=led, validation_store=vstore, issued_store=istore,
                                    realized=realized, as_of=args.as_of)
                print(f"tips run-eod [{','.join(unds)}] source={res['source']}: issued {res['issued']}  "
                      f"headline {len(res['headline'])}  watchlist {len(res['watchlist'])}  "
                      f"resolved {res['resolved']}")
                for t in res["headline"][:10]:
                    print(f"  HEADLINE  {t['underlying']} {t['structure']} {t['direction']}  "
                          f"conv={t['conviction']}  cost-adj EV={t['cost_adjusted_ev']}")
                for t in res["watchlist"][:5]:
                    print(f"  watch     {t['underlying']} {t['structure']} {t['direction']}  "
                          f"conv={t['conviction']}  cost-adj EV={t['cost_adjusted_ev']}")
        finally:
            led.close()
            vstore.close()
            istore.close()
        return 0

    if args.action == "run-live":
        from .tips.intraday import run_intraday

        unds = [u.strip().upper() for u in args.underlyings.split(",")]
        market_open = _is_market_open()
        if not market_open:
            print("market is closed — issuing one pass against the resolved source (demo/cached).")
        res = run_intraday(unds)
        print(f"tips run-live [{','.join(unds)}] source={res['source']}: issued {res['issued']}  "
              f"headline {len(res['headline'])}  watchlist {len(res['watchlist'])}")
        for t in (res["headline"] + res["watchlist"])[:8]:
            print(f"  {t['tier']:<9} {t['underlying']} {t['structure']} {t['direction']}  "
                  f"conv={t['conviction']}  cost-adj EV={t['cost_adjusted_ev']}")
        return 0

    print(f"unknown tips action {args.action}")
    return 2


def _is_market_open() -> bool:
    """Best-effort NSE cash-session check (Mon-Fri 09:15-15:30 IST). Used only to label the live
    pass; the pass still runs (against the resolved source) when closed, so a smoke test works."""
    try:
        from datetime import datetime, timedelta, timezone

        ist = timezone(timedelta(hours=5, minutes=30))
        now = datetime.now(ist)
        if now.weekday() >= 5:
            return False
        mins = now.hour * 60 + now.minute
        return 9 * 60 + 15 <= mins <= 15 * 60 + 30
    except Exception:  # noqa: BLE001
        return False


def _print_paper_report(rep: dict) -> None:
    line = "─" * 64
    m = rep.get("meta", {})
    s, t, r = rep["summary"], rep["trades"], rep["risk"]
    print(line)
    print(f"  PAPER SESSION REPORT — {m.get('mode', 'replay')}  [{','.join(m.get('underlyings', []))}]"
          f"  source={m.get('source')}  seed={m.get('seed')}")
    print(line)
    print("  ACCOUNT")
    print(f"    capital {_fmt(s['starting_capital'])} → equity {_fmt(s['ending_equity'])}   "
          f"net P&L {_fmt(s['net_pnl'])}  ({_fmt(s['return_pct'],3)}%)   realized {_fmt(s['realized_pnl'])}")
    print("  TRADES")
    wr = (t["win_rate"] or 0) * 100
    print(f"    closed {t['n_total']}   win-rate {_fmt(wr,0)}%   profit-factor {_fmt(t['profit_factor'],2)}   "
          f"expectancy {_fmt(t['expectancy'])}")
    print(f"    best {_fmt(t['best'])}   worst {_fmt(t['worst'])}")
    print("  RISK")
    print(f"    max drawdown {_fmt((r['max_drawdown'] or 0)*100,2)}%   Sharpe {_fmt(r['sharpe_annualized'],2)}   "
          f"Sortino {_fmt(r['sortino_annualized'],2)}   avg exposure {_fmt(r['avg_gross_exposure'])}")
    by = rep["attribution"]["by_strategy"]
    if by:
        print("  ATTRIBUTION (by strategy)")
        for name, b in sorted(by.items(), key=lambda kv: kv[1]["net_pnl"], reverse=True):
            print(f"    {name:20s} n={b['n']:<3d} net {_fmt(b['net_pnl']):>12}   win-rate {_fmt(b['win_rate']*100,0)}%")
    pl = rep.get("performance_lab", {}).get("aggregates", {})
    if pl:
        print("  PERFORMANCE LAB")
        print(f"    avg MAE {_fmt(pl.get('avg_mae'))}   avg MFE {_fmt(pl.get('avg_mfe'))}   "
              f"slippage {_fmt(pl.get('total_slippage_cost'))}   charges {_fmt(pl.get('total_charges'))}")
        print(f"    mean conviction {_fmt((pl.get('mean_conviction') or 0)*100,0)}%   "
              f"realized win-rate {_fmt((pl.get('realized_win_rate') or 0)*100,0)}%")
    cc = rep.get("conviction_calibration")
    if cc:
        cs = (cc.get("calibration_score") or {})
        sc = cs.get("score")
        print("  CONVICTION CALIBRATION (paper-only; excluded from the public moat)")
        print(f"    resolved {cc['resolved_count']}   "
              f"score {(str(sc)+'/100') if sc is not None else cs.get('rating', '—')}"
              + (f"   Brier {cc['brier']:.4f}" if cc.get("brier") is not None else ""))
    if rep.get("missed_opportunities"):
        print(f"  MISSED (governor-rejected): {len(rep['missed_opportunities'])}")
    print(line)
    print("  " + rep.get("caveat", "Paper simulation — not investment advice."))
    print(line)


def _default_session(args) -> tuple[str, str]:
    today = date.today()
    start = args.start or f"{today.isoformat()}T03:45:00+00:00"  # ~09:15 IST
    if args.expiry:
        return start, args.expiry
    d = today + timedelta(days=1)
    while d.weekday() != 3:  # next Thursday (weekly index expiry)
        d += timedelta(days=1)
    return start, d.isoformat()


def cmd_paper(args) -> int:
    """Personal paper-trading mock loop (gated). `replay` = deterministic full session + report."""
    from .config import SETTINGS

    if not SETTINGS.paper_trading:
        print("paper trading is disabled (PAPER_TRADING=false).")
        return 2
    from .live.realtime import RealtimeEngine
    from .paper.account import PaperBook

    unds = [u.strip().upper() for u in (args.underlying or "NIFTY").split(",")]

    if args.action == "replay":
        led = None
        if not args.no_ledger:
            from .ledger.ledger import CalibrationLedger
            led = CalibrationLedger(args.ledger_path) if args.ledger_path else CalibrationLedger()
        start, expiry = _default_session(args)
        book = PaperBook(starting_capital=args.capital)
        eng = RealtimeEngine(book=book, ledger=led)
        try:
            rep = eng.replay(unds, start_ts=start, expiry=expiry, steps=args.steps,
                             cadence_s=args.cadence, seed=args.seed,
                             source_label=("demo" if args.demo else "replay"))
        finally:
            if led is not None:
                led.close()
        if args.json:
            print(json.dumps(rep, indent=2, default=str))
        else:
            _print_paper_report(rep)
        return 0

    if args.action == "run":
        from .live.chain_source import LiveChainSource
        from .live.clock import LiveClock
        from .strategy import SignalContext

        src = LiveChainSource(args.source)
        clock = LiveClock(args.cadence)
        eng = RealtimeEngine(book=PaperBook(starting_capital=args.capital))
        recorder = None
        if args.record:
            from .live.recorder import TickRecorder

            recorder = TickRecorder()
        ticks = 0
        print(f"live paper run [{args.source or SETTINGS.primary_data_source}] cadence {args.cadence}s — Ctrl-C to stop")
        try:
            while ticks < args.steps:
                ts = clock.tick()
                if ts is None:
                    print("market closed — stopping live run (use `paper replay` off-hours).")
                    break
                for u in unds:
                    chain = src.chain(u)
                    ctx = SignalContext(chain, iv_history=list(eng.iv_history.get(u, [])), source="live")
                    eng.run_tick(ctx, ts)
                    if recorder is not None:
                        recorder.record_chain(chain, "live")  # capture for post-close replay alignment
                ep = eng.book.record_equity_point(ts)
                print(f"  {ts}  equity {_fmt(ep.equity)}  open {ep.open_positions}  realized {_fmt(ep.realized_pnl)}")
                ticks += 1
                if ticks < args.steps:
                    import time as _t
                    _t.sleep(args.cadence)
        finally:
            if recorder is not None:
                recorder.close()
        _print_paper_report(run_report_for(eng))
        return 0
    return 0


def run_report_for(eng) -> dict:
    from .paper.report import run_report

    return run_report(eng.book, ledger=eng.ledger, missed=eng.missed, meta={"mode": "realtime"})


def cmd_calibrate(args) -> int:
    """Fit / report the probability calibrators (Phase 2). Quality is measured OUT-OF-FOLD; maps are
    fit PER source-class (the firewall) and degrade to identity when there isn't enough data."""
    from datetime import datetime, timezone

    from .backtest.trials import TrialRegistry
    from .calibration import CALIBRATION_VERSION
    from .calibration.service import fit_all_targets
    from .calibration.store import CalibratorStore
    from .config import SETTINGS
    from .ledger.ledger import CalibrationLedger

    led = CalibrationLedger(args.ledger_path) if args.ledger_path else CalibrationLedger()
    store = CalibratorStore(args.store_path) if args.store_path else CalibratorStore()
    try:
        if args.action == "fit":
            trials = TrialRegistry(args.store_path) if args.store_path else TrialRegistry()
            try:
                summary = fit_all_targets(
                    ledger=led, store=store, min_samples=args.min_samples,
                    blend_floor_n=SETTINGS.calibration_blend_floor_n,
                    accuracy_floor=SETTINGS.calibration_accuracy_floor,
                    n_splits=SETTINGS.calibration_n_splits,
                    now_ts=datetime.now(timezone.utc).isoformat(), trial_registry=trials,
                    only_source_class=args.source_class)
            finally:
                trials.close()
            print(f"calibrate fit [{CALIBRATION_VERSION}] — {len(summary)} (target, source-class) maps:")
            _print_calibrators(store.all())
        elif args.action == "report":
            _print_calibrators(store.all())
    finally:
        led.close()
        store.close()
    return 0


def cmd_gate0(args) -> int:
    """Gate-0 — the kill switch. Walk-forward, per target, the decision threshold chosen INSIDE the loop
    and COUNTED as a trial: does the high-confidence bucket sustain usable CALIBRATED accuracy at usable
    coverage, with positive EV net of cost and the full anti-overfit battery? Honest discovery — an
    ABSTAIN ('not enough evidence yet') is a valid, correct outcome, not something to tune away."""
    from datetime import date, datetime, timezone
    from pathlib import Path

    from .backtest import BhavcopyArchive
    from .backtest.gate0 import run_gate0
    from .backtest.gate_report import write_gate0_report
    from .backtest.tip_backtest import run_tip_backtest
    from .backtest.trials import TrialRegistry
    from .calibration.service import fit_all_targets
    from .calibration.store import CalibratorStore
    from .config import SETTINGS
    from .ledger.ledger import CalibrationLedger
    from .tips.store import IssuedTipStore, TipValidationStore

    cache = Path(args.cache_dir)
    if not cache.exists():
        print(f"cache dir {cache} not found — run: anvil data backfill --start … --end …")
        return 2
    start = date.fromisoformat(args.start) if args.start else None
    end = date.fromisoformat(args.end) if args.end else None
    unds = [u.strip().upper() for u in args.underlyings.split(",")]
    trade_sc = args.source_class or "tip_backtest"
    struct_sc = "struct_live" if trade_sc.endswith("live") else "struct_backtest"

    led = CalibrationLedger(args.ledger_path) if args.ledger_path else CalibrationLedger()
    vstore = TipValidationStore(args.store_path) if args.store_path else TipValidationStore()
    istore = IssuedTipStore(args.store_path) if args.store_path else IssuedTipStore()
    cstore = CalibratorStore(args.store_path) if args.store_path else CalibratorStore()
    trials = TrialRegistry(args.store_path) if args.store_path else TrialRegistry()
    result = None
    try:
        if args.trials:
            trials.bump(f"gate0:{trade_sc}", int(args.trials))
            print(f"trial registry: +{args.trials} declared configs (raises the Deflated-Sharpe bar)")

        arch = BhavcopyArchive.from_cache_dir(cache)
        tdays = arch.trading_days(start, end)
        depth = len(tdays)
        rng = (tdays[0].isoformat(), tdays[-1].isoformat()) if depth else None

        # 1) Evidence — option tips (+ optional equities), persisting resolved tips (with ret) to the
        #    issued store so Gate-0 reads calibrated accuracy AND EV from one aligned source.
        ro = run_tip_backtest(arch, unds, led, vstore, start=start, end=end,
                              max_expiries=args.max_expiries, issued_store=istore, source=trade_sc)
        print(f"options backtest [{','.join(unds)}]: issued {ro['recorded']}  resolved {ro['resolved']}  "
              f"cells {ro['cells']}")
        if args.equities:
            from .tips.equities import discover_universe, run_equity_backtest

            uni = discover_universe(cache, top_n=args.universe_size)
            earch = BhavcopyArchive.from_cache_dir(cache, universe=set(uni))
            re = run_equity_backtest(earch, uni, led, vstore, start=start, end=end,
                                     top_k=args.top_k, issued_store=istore, source=trade_sc)
            print(f"equity backtest [{len(uni)} stocks]: issued {re['recorded']}  resolved {re['resolved']}")
        if not args.no_structural:
            try:
                from .backtest import run_backtest

                rs = run_backtest(arch, unds, led, start=start, end=end)
                print(f"structural backtest: recorded {rs.get('recorded')}  resolved {rs.get('resolved')}")
            except Exception as e:  # noqa: BLE001 - structural is best-effort for the dry-run
                print(f"structural backtest skipped: {e}")

        # 2) Calibrate per (target, source-class) from the resolved ledger history (OOF honesty guard).
        now_ts = datetime.now(timezone.utc).isoformat()
        fit_all_targets(ledger=led, store=cstore, min_samples=args.min_samples,
                        blend_floor_n=SETTINGS.calibration_blend_floor_n,
                        accuracy_floor=args.accuracy_floor, n_splits=SETTINGS.calibration_n_splits,
                        now_ts=now_ts, trial_registry=trials)
        service = cstore.load_service()

        # 3) Gate-0 — per-target accuracy/EV at coverage, in-loop trial-counted thresholds, full battery.
        result = run_gate0(
            issued_store=istore, ledger=led, calibrators=service,
            sources={"trade": (trade_sc,), "struct": (struct_sc,)},
            accuracy_target=args.accuracy_target, min_coverage=args.min_coverage,
            accuracy_floor=args.accuracy_floor, min_samples=args.min_samples,
            trial_registry=trials, now_ts=now_ts, date_range=rng, depth_days=depth,
            provisional=not args.full_depth)
        paths = write_gate0_report(result, args.out, now_ts=now_ts)
    finally:
        led.close()
        vstore.close()
        istore.close()
        cstore.close()
        trials.close()

    v = result["verdict"]
    print()
    print(f"GATE-0 {'✅ GO' if v['pass'] else '⛔ NO-GO / ABSTAIN'} — {v['summary']}")
    for t in result["targets"]:
        if t.get("evaluable"):
            flag = "PASS" if t.get("verdict", {}).get("pass") else "abstain"
            print(f"  {t['target']:<11}/{t['source_class']:<15} n={t['n']:<4} "
                  f"cov={_fmt_num(t.get('coverage'), 3)} acc={_fmt_num(t.get('accuracy'), 3)} "
                  f"ev={_fmt_num(t.get('realized_ev'), 4)} tau={_fmt_num(t.get('operating_tau'), 2)} [{flag}]")
        else:
            print(f"  {t['target']:<11}/{t['source_class']:<15} n={t['n']:<4} [{t.get('note', 'abstain')}]")
    print(f"\nreport: {paths['markdown']}  |  {paths['json']}  |  {paths['svg']}")
    return 0


def _fmt_num(v, nd: int = 4) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "—"
    return "—" if f != f else f"{f:.{nd}f}"  # NaN → em dash


def _print_calibrators(rows: list[dict]) -> None:
    if not rows:
        print("  (no calibrators fit yet)")
        return
    print(f"  {'target':<11} {'class':<15} {'kind':<9} {'n':>5} {'folds':>5} "
          f"{'ECE_before':>10} {'ECE_after':>10} {'tau':>6} {'λ':>5}")
    for r in sorted(rows, key=lambda x: (x.get("target", ""), x.get("source_class", ""))):
        tau = r.get("abstain_tau")
        print(f"  {r.get('target',''):<11} {r.get('source_class',''):<15} {r.get('kind',''):<9} "
              f"{int(r.get('n') or 0):>5} {int(r.get('n_folds') or 0):>5} "
              f"{_fmt_num(r.get('ece_before')):>10} {_fmt_num(r.get('ece_after')):>10} "
              f"{(_fmt_num(tau, 3) if tau is not None else '—'):>6} {_fmt_num(r.get('lambda_blend'),2):>5}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="anvil", description="Anvil options intelligence engine")
    sub = p.add_subparsers(dest="cmd", required=True)

    pull = sub.add_parser("pull", help="pull a chain and print/persist analytics")
    pull.add_argument("underlying", nargs="?", default="NIFTY")
    pull.add_argument("--demo", action="store_true", help="use offline synthetic data (no keys)")
    pull.add_argument("--source", default=None, help="demo|upstox|dhan (overrides env)")
    pull.add_argument("--expiry", default=None, help="ISO date; default = nearest")
    pull.add_argument("--store", action="store_true", help="persist a snapshot to the store")
    pull.add_argument("--json", action="store_true", help="emit raw JSON")
    pull.set_defaults(func=cmd_pull)

    mcp = sub.add_parser("mcp-check", help="introspect a hosted MCP endpoint (tools/list)")
    mcp.add_argument("--url", default=None)
    mcp.add_argument("--token", default=None)
    mcp.set_defaults(func=cmd_mcp_check)

    serve = sub.add_parser("serve", help="run the FastAPI app")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")
    serve.set_defaults(func=cmd_serve)

    cert = sub.add_parser(
        "cert", help="full-depth certification: parallel streaming backtest across the cache → cells → gate verdict")
    cert.add_argument("action", choices=["full"])
    cert.add_argument("--underlyings", default="NIFTY,BANKNIFTY")
    cert.add_argument("--cache-dir", default="data/bhavcopy_cache")
    cert.add_argument("--start", default=None, help="ISO start date (default: whole cache)")
    cert.add_argument("--end", default=None, help="ISO end date")
    cert.add_argument("--workers", type=int, default=0, help="parallel processes (0/1 = serial)")
    cert.add_argument("--equities", action="store_true", help="also certify the single-stock equity engine")
    cert.add_argument("--universe-size", type=int, default=40, help="equities: top-N liquid names")
    cert.add_argument("--max-expiries", type=int, default=2, help="nearest N expiries to score")
    cert.add_argument("--trials", type=int, default=0, help="declare a config sweep (raises the DSR bar)")
    cert.add_argument("--store-path", default=None, help="TipValidationStore path (default: SETTINGS.store_path)")
    cert.add_argument("--ledger-path", default=None)
    cert.set_defaults(func=cmd_cert)

    golive = sub.add_parser(
        "go-live", help="one process: REST API + live cockpit supervisor (recorder + predictions + nightly moat clock)")
    golive.add_argument("--host", default="127.0.0.1")
    golive.add_argument("--port", type=int, default=8000)
    golive.add_argument("--underlyings", default=None, help="comma-separated cockpit underlyings (default from config)")
    golive.add_argument("--force-open", action="store_true", help="run the cockpit even outside market hours (demo)")
    golive.add_argument("--no-prep", action="store_true", help="skip startup prep (token check + instruments + closes)")
    golive.set_defaults(func=cmd_go_live)

    led = sub.add_parser("ledger", help="calibration ledger (record/resolve/seed/report/run-daily)")
    led.add_argument("action", choices=["record", "resolve", "seed", "report", "run-daily"])
    led.add_argument("underlying", nargs="?", default="NIFTY",
                     help="underlying, or comma-separated list for run-daily")
    led.add_argument("--demo", action="store_true", help="use offline synthetic data")
    led.add_argument("--source", default=None, help="demo|upstox|dhan")
    led.add_argument("--expiry", default=None)
    led.add_argument("--realized", type=float, default=None, help="realized index level (resolve)")
    led.add_argument("--as-of", default=None, help="ISO ts treated as 'now' for resolve")
    led.add_argument("--n", type=int, default=600, help="count for seed")
    led.add_argument("--full", action="store_true",
                     help="run-daily: full moat clock (snapshot + tips + revalidate via run_daily_cycle)")
    led.set_defaults(func=cmd_ledger)

    bt = sub.add_parser("backtest", help="real out-of-sample calibration from EOD bhavcopy history")
    bt.add_argument("action", choices=["run", "fetch"])
    bt.add_argument("--cache-dir", default="data/bhavcopy_cache", help="dir of cached F&O bhavcopy CSVs")
    bt.add_argument("--underlyings", default="NIFTY", help="comma-separated, e.g. NIFTY,BANKNIFTY")
    bt.add_argument("--start", default=None, help="ISO date (inclusive)")
    bt.add_argument("--end", default=None, help="ISO date (inclusive)")
    bt.set_defaults(func=cmd_backtest)

    tips = sub.add_parser("tips", help="short-term tips engine: backtest the gate / run the EOD or live cycle")
    tips.add_argument("action", choices=["backtest", "run-eod", "run-live"])
    tips.add_argument("--cache-dir", default="data/bhavcopy_cache", help="dir of cached F&O bhavcopy CSVs")
    tips.add_argument("--underlyings", default="NIFTY", help="comma-separated, e.g. NIFTY,BANKNIFTY")
    tips.add_argument("--start", default=None, help="ISO date (inclusive)")
    tips.add_argument("--end", default=None, help="ISO date (inclusive)")
    tips.add_argument("--min-samples", type=int, default=50, help="resolved tips per cell before headline-eligible")
    tips.add_argument("--realized", type=float, default=None, help="realized close to settle DUE tips (run-eod)")
    tips.add_argument("--as-of", default=None, help="ISO date treated as the cycle/resolution day (run-eod)")
    tips.add_argument("--ledger-path", default=None, help="DuckDB ledger path (default: configured)")
    tips.add_argument("--store-path", default=None, help="DuckDB store path for tip_validation (default: configured)")
    tips.add_argument("--equities", action="store_true", help="single-stock BUY/SELL engine (else index options)")
    tips.add_argument("--top-k", type=int, default=5, help="equities: longs/shorts to issue per day")
    tips.add_argument("--universe-size", type=int, default=40, help="equities: most-liquid F&O stocks to scan")
    tips.add_argument("--max-expiries", type=int, default=2, help="options backtest: nearest N expiries to score")
    tips.add_argument("--trials", type=int, default=0,
                      help="configs swept this session (logged to the trial registry; raises the "
                           "Deflated-Sharpe bar honestly so a threshold/target sweep can't sneak through)")
    tips.add_argument("--cadence", type=int, default=120, help="run-live: seconds between passes")
    tips.set_defaults(func=cmd_tips)

    auth = sub.add_parser("auth", help="broker login (upstox/kite/groww) or token status")
    auth.add_argument("provider", choices=["upstox", "kite", "groww", "status"])
    auth.add_argument("--request-token", default=None, help="Kite request_token from the redirect")
    auth.add_argument("--api-key", default=None, help="Kite api_key (for the login URL)")
    auth.set_defaults(func=cmd_auth)

    order = sub.add_parser("order", help="assisted order (DRY-RUN unless --live); auto-exec stays OFF")
    order.add_argument("symbol")
    order.add_argument("side", choices=["BUY", "SELL", "buy", "sell"])
    order.add_argument("qty", type=int)
    order.add_argument("--type", default="LIMIT", help="MARKET|LIMIT|STOP_LOSS|STOP_LOSS_MARKET")
    order.add_argument("--price", type=float, default=None)
    order.add_argument("--product", default="NRML", help="NRML|MIS|CNC")
    order.add_argument("--exchange", default="NSE")
    order.add_argument("--segment", default="FNO", help="FNO|CASH")
    order.add_argument("--rationale", default=None)
    order.add_argument("--live", action="store_true", help="arm real placement (still asks to confirm)")
    order.add_argument("--yes", action="store_true", help="skip the confirm prompt")
    order.set_defaults(func=cmd_order)

    paper = sub.add_parser("paper", help="personal paper-trading mock loop (replay/run) + effectiveness report")
    paper.add_argument("action", choices=["replay", "run"])
    paper.add_argument("--underlying", default="NIFTY", help="comma-separated, e.g. NIFTY,BANKNIFTY")
    paper.add_argument("--capital", type=float, default=None, help="starting paper capital (INR)")
    paper.add_argument("--seed", type=int, default=7, help="replay RNG seed (determinism)")
    paper.add_argument("--steps", type=int, default=20, help="number of ticks")
    paper.add_argument("--cadence", type=int, default=7200, help="seconds between ticks")
    paper.add_argument("--start", default=None, help="ISO start timestamp (default: today 09:15 IST)")
    paper.add_argument("--expiry", default=None, help="ISO expiry date (default: next weekly Thursday)")
    paper.add_argument("--source", default=None, help="live source for `run` (upstox|groww|…)")
    paper.add_argument("--demo", action="store_true", help="label the replay source as demo")
    paper.add_argument("--no-ledger", action="store_true", help="skip conviction calibration recording")
    paper.add_argument("--ledger-path", default=None, help="DuckDB ledger path (default: configured)")
    paper.add_argument("--record", action="store_true", help="record live ticks to the store (run mode; for replay alignment)")
    paper.add_argument("--json", action="store_true", help="emit the full report as JSON")
    paper.set_defaults(func=cmd_paper)

    record = sub.add_parser("record", help="always-on intraday option-chain recorder (run under Task Scheduler)")
    record.add_argument("action", choices=["run"])
    record.add_argument("--underlyings", default="NIFTY,BANKNIFTY,SENSEX", help="comma-separated")
    record.add_argument("--cadence", type=int, default=60, help="seconds between snapshots")
    record.add_argument("--source", default=None, help="demo|upstox|dhan|groww (default: auto-resolve live)")
    record.add_argument("--once", action="store_true", help="record a single cycle then exit (cron-per-minute)")
    record.add_argument("--force-open", action="store_true", help="ignore market-hours gating (testing/backfill)")
    record.add_argument("--max-ticks", type=int, default=0, help="stop after N ticks (0 = until the close)")
    record.set_defaults(func=cmd_record)

    data = sub.add_parser("data", help="data ops: Yahoo closes, candles, instruments, NSE F&O backfill, positioning, health")
    data.add_argument("action", choices=["fetch-closes", "fetch-candles", "fetch-instruments",
                                         "build-bars", "backfill", "health", "fetch-positioning"])
    data.add_argument("--symbols", default="^NSEI,^NSEBANK,^INDIAVIX", help="comma-separated Yahoo symbols")
    data.add_argument("--underlyings", default=None, help="comma-separated underlyings (candles/build-bars)")
    data.add_argument("--tf", default=None, help="comma-separated timeframes, e.g. 1m,5m,1h,1d (candles/build-bars)")
    data.add_argument("--intraday", action="store_true", help="fetch-candles: pull today's intraday candles")
    data.add_argument("--source", default=None, help="force a connector (upstox/demo); default auto-live")
    data.add_argument("--range", default="2y", help="Yahoo range (e.g. 1y,2y,5y)")
    data.add_argument("--cache-dir", default="data/bhavcopy_cache", help="bhavcopy cache dir (backfill/health)")
    data.add_argument("--start", default=None, help="ISO start date (backfill)")
    data.add_argument("--end", default=None, help="ISO end date (backfill)")
    data.add_argument("--years", type=float, default=None, help="backfill the last N years up to today")
    data.add_argument("--workers", type=int, default=3, help="backfill: concurrent fetches (be polite)")
    data.add_argument("--log", default=None, help="backfill: checkpoint log path (default: <cache-dir>/backfill.log)")
    data.add_argument("--date", default=None, help="ISO date for fetch-positioning (default: latest trading day)")
    data.set_defaults(func=cmd_data)

    db = sub.add_parser("decision-brief", help="buyer Decision Brief: environment-gate → strike-action P(touch)")
    db.add_argument("underlying", help="e.g. NIFTY")
    db.add_argument("--horizon", type=int, default=5, help="touch horizon in trading days")
    db.add_argument("--range", default="2y", help="Yahoo history range for RV/regime")
    db.add_argument("--source", default=None, help="data source (demo|upstox|…); default resolved")
    db.add_argument("--record", action="store_true", help="record touch/VRP forecasts for calibration")
    db.add_argument("--ledger-path", default=None, help="DuckDB ledger path (default: configured)")
    db.set_defaults(func=cmd_decision_brief)

    cal = sub.add_parser("calibrate", help="fit/report probability calibrators (isotonic/Platt; OOF quality)")
    cal.add_argument("action", choices=["fit", "report"])
    cal.add_argument("--source-class", default=None,
                     help="fit only this class (tip_backtest|tip_live|struct_backtest|struct_live)")
    cal.add_argument("--min-samples", type=int, default=50, help="below this n a target stays identity")
    cal.add_argument("--ledger-path", default=None, help="DuckDB ledger path (default: configured)")
    cal.add_argument("--store-path", default=None, help="DuckDB store path for calibrators (default: configured)")
    cal.set_defaults(func=cmd_calibrate)

    g0 = sub.add_parser("gate0", help="Gate-0 kill switch: per-target calibrated accuracy + EV at "
                                      "coverage, in-loop trial-counted thresholds, full battery")
    g0.add_argument("--cache-dir", default="data/bhavcopy_cache", help="dir of cached F&O bhavcopy CSVs")
    g0.add_argument("--underlyings", default="NIFTY,BANKNIFTY", help="comma-separated, e.g. NIFTY,BANKNIFTY")
    g0.add_argument("--start", default=None, help="ISO date (inclusive)")
    g0.add_argument("--end", default=None, help="ISO date (inclusive)")
    g0.add_argument("--source-class", default="tip_backtest",
                    help="trade-win source class to certify (tip_backtest|tip_live)")
    g0.add_argument("--accuracy-target", type=float, default=0.65, help="calibrated-accuracy pass bar")
    g0.add_argument("--min-coverage", type=float, default=0.10, help="coverage pass bar")
    g0.add_argument("--accuracy-floor", type=float, default=0.52, help="breakeven floor for the frontier")
    g0.add_argument("--min-samples", type=int, default=8, help="independent act-days per threshold cell")
    g0.add_argument("--max-expiries", type=int, default=2, help="options: nearest N expiries to score")
    g0.add_argument("--equities", action="store_true", help="also run the single-stock equity engine")
    g0.add_argument("--no-structural", action="store_true", help="skip the touch/VRP structural backtest")
    g0.add_argument("--full-depth", action="store_true",
                    help="mark the report NON-provisional (use only on the full backfill)")
    g0.add_argument("--out", default="reports/gate0", help="output dir for gate0.{md,json,svg}")
    g0.add_argument("--trials", type=int, default=0, help="extra declared configs swept (raises the bar)")
    g0.add_argument("--top-k", type=int, default=5, help="equities: longs/shorts to issue per day")
    g0.add_argument("--universe-size", type=int, default=40, help="equities: most-liquid F&O stocks to scan")
    g0.add_argument("--ledger-path", default=None, help="DuckDB ledger path (default: configured)")
    g0.add_argument("--store-path", default=None, help="DuckDB store path (default: configured)")
    g0.set_defaults(func=cmd_gate0)
    return p


def main(argv=None) -> int:
    # Windows consoles default to cp1252 and choke on σ/→/δ etc. Emit UTF-8.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
