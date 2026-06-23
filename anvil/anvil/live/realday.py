"""'Today' real-day replay — reconstruct today's REAL trading day, run the paper strategy along it,
and GRADE the day's predictions against the real close.

Synchronous (reuses the replay machinery); works with the market CLOSED. For each underlying it:
  1) snapshots the real chain (``RealDaySource``) and records two forecast sets —
     - expiry-horizon (``emit_forecasts`` at the real connector name → public ``live`` moat, resolved
       later by the daily cycle), and
     - intraday-horizon band+direction (resolve_ts = today's close, owner-only ``today`` class) for the
       per-session scorecard;
  2) walks the real intraday candles, repricing the chain and running ``engine.run_tick``;
  3) flattens at the close and resolves the intraday predictions against the real EOD close.

When the data source is demo (no broker), forecasts are stamped ``demo`` so they can never enter the
public calibration curve. Returns ``(engine, report)`` with ``report['prediction_scorecard']`` attached.
"""

from __future__ import annotations

import math

from ..engine.implied_dist import implied_distribution
from ..ledger.ledger import KIND_PROB_ABOVE, KIND_PROB_IN_BAND, Forecast, emit_forecasts
from ..paper.report import run_report
from ..strategy import SignalContext
from .realday_source import RealDaySource


def _intraday_forecasts(src: RealDaySource, dist, source: str) -> tuple[list[Forecast], dict]:
    """1-trading-day-horizon band+direction forecasts centered on the day's OPEN, resolved at the
    close. The implied expiry expected-move is scaled by sqrt(1/days_to_expiry) (sqrt-time)."""
    if dist is None:
        return [], {}
    a = src.anchor_chain
    open_px = src.day_open()
    days = max(float(dist.expiry_T) * 365.0, 1.0)
    # Scale the EXPIRY-horizon expected move down to a single trading day (sqrt-time). Prefer the
    # ATM-IV move (F*iv*sqrt(T)) over the RND std (expected_move_1sigma), whose tail extrapolation
    # inflates the variance ~2-3x and would make the intraday band trivially wide.
    em_expiry = float(dist.em_atm_iv or dist.expected_move_1sigma)
    em_today = em_expiry * math.sqrt(1.0 / days)
    close_ts = src.timestamps()[-1]
    fwd = float(getattr(dist, "forward", open_px))

    def mk(kind, params, prob):
        return Forecast(
            underlying=src.underlying, created_ts=a.timestamp, resolve_ts=close_ts, kind=kind,
            params=params, prob=float(prob), spot=float(open_px), forward=fwd, source=source,
        )

    fc = [
        mk(KIND_PROB_IN_BAND, {"lower": open_px - em_today, "upper": open_px + em_today, "nominal": "1sigma_intraday"}, 0.6827),
        mk(KIND_PROB_IN_BAND, {"lower": open_px - 0.5 * em_today, "upper": open_px + 0.5 * em_today, "nominal": "0.5sigma_intraday"}, 0.3829),
        mk(KIND_PROB_ABOVE, {"level": open_px, "horizon": "intraday"}, 0.5),
    ]
    meta = {
        "underlying": src.underlying,
        "open": round(open_px, 2),
        "expected_move_1sigma": round(em_today, 2),
        "band_1sigma": [round(open_px - em_today, 2), round(open_px + em_today, 2)],
        "band_half_sigma": [round(open_px - 0.5 * em_today, 2), round(open_px + 0.5 * em_today, 2)],
        "predicted": {"p_in_1sigma": 0.683, "p_in_half_sigma": 0.383, "p_above_open": 0.5},
        "smile": "frozen at snapshot (realday_smile_held) — a model estimate, not historical quotes",
    }
    return fc, meta


def _finalize_scorecard(meta: dict, real_close: float) -> dict:
    if not meta:
        return meta
    o = meta["open"]
    lo, hi = meta["band_1sigma"]
    hlo, hhi = meta["band_half_sigma"]
    in1 = bool(lo <= real_close <= hi)
    above = bool(real_close >= o)
    meta["realized_close"] = round(real_close, 2)
    meta["move"] = round(real_close - o, 2)
    meta["hits"] = {
        "in_1sigma": in1,
        "in_half_sigma": bool(hlo <= real_close <= hhi),
        "above_open": above,
    }
    events = [(0.683, 1.0 if in1 else 0.0), (0.5, 1.0 if above else 0.0)]
    meta["brier"] = round(sum((p - e) ** 2 for p, e in events) / len(events), 4)
    return meta


def run_today(engine, underlyings, conn, *, ledger=None, interval_min: int = 15, source_label: str = "today"):
    """Drive a real-day replay across one or more underlyings. Returns (engine, report)."""
    unds = [u.upper() for u in underlyings]
    sources = {u: RealDaySource(u, conn, interval_min=interval_min) for u in unds}
    fc_source = "demo" if getattr(conn, "name", "") == "demo" else "today"

    scorecards: dict[str, dict] = {}
    for u in unds:
        src = sources[u]
        dist = implied_distribution(src.anchor_chain)
        if ledger is not None and dist is not None:
            # Expiry-horizon, real market-implied -> public moat (or 'demo' when degraded).
            ledger.record_many(emit_forecasts(src.anchor_chain, dist, source=getattr(conn, "name", "demo")))
        intraday_fc, meta = _intraday_forecasts(src, dist, source=fc_source)
        if ledger is not None and intraday_fc:
            ledger.record_many(intraday_fc)
        scorecards[u] = meta

    # The candle grids are aligned (same session); drive on the first underlying's timestamps.
    ts_list = sources[unds[0]].timestamps()
    last_ctx: dict[str, SignalContext] = {}
    for step, ts in enumerate(ts_list):
        for u in unds:
            chain = sources[u].chain(ts, step)
            ctx = SignalContext(chain, iv_history=list(engine.iv_history.get(u, [])), source=source_label)
            engine.run_tick(ctx, ts)
            last_ctx[u] = ctx
        engine.book.record_equity_point(ts)

    for ctx in last_ctx.values():
        engine.book.flatten(ctx, reason="session_end")
    engine._resolve_new_closed()

    close_ts = ts_list[-1]
    for u in unds:
        real_close = sources[u].spot_at(len(ts_list) - 1)
        if ledger is not None:
            ledger.resolve_due(u, real_close, as_of=close_ts)
        scorecards[u] = _finalize_scorecard(scorecards[u], real_close)

    meta = {
        "mode": "today", "underlyings": unds, "steps": len(ts_list), "cadence_s": interval_min * 60,
        "source": getattr(conn, "name", "demo"), "start_ts": ts_list[0], "end_ts": close_ts,
        "smile_basis": "realday_smile_held",
    }
    report = run_report(engine.book, ledger=ledger, missed=engine.missed, meta=meta)
    report["prediction_scorecard"] = scorecards
    return engine, report
