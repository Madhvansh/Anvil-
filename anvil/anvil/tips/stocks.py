"""Live, chain-driven single-stock tips — stage 2 of the funnel (the real per-stock analysis).

Each selected stock is run through the SAME full pipeline as the index: live option chain (greeks/IV/
OI/skew/GEX) + daily-momentum series → ``predict_for_chain`` → one calibrated, factor-explained
directional read. The results are ranked cross-sectionally into BUY/SELL, so conviction is genuinely
differentiated (driven by the whole factor stack), never the old flat 0.62 momentum-only cap.

Concurrency: a bounded ``ThreadPoolExecutor`` fans the per-stock chain fetches out over ONE shared
connector (httpx is thread-safe). The DuckDB validation store is NOT thread-safe, so the parallel pass
runs with ``validation_store=None`` and the edge/tier verdict is attached single-threaded afterwards
from the pooled ``EQUITY`` cell (the same honesty rail the EOD equities engine uses).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from ..config import SETTINGS
from ..ingest.base import attach_parity_forward
from ..strategy.types import BEARISH, BULLISH
from .equities import EQUITY_BUCKET, EQUITY_POOL, EQUITY_STRUCTURE, _HORIZON, _STOP_PCT, _TARGET_PCT
from .predict import predict_for_chain
from .series import build_series_block


def _stock_series(conn, symbol: str) -> dict:
    """Daily-close series for stock momentum — live from the connector's candles, Yahoo cache as
    fallback. Keeps stock momentum real (live) and independent of whether Yahoo was pre-cached."""
    try:
        to_d = datetime.now(timezone.utc).date()
        from_d = to_d - timedelta(days=400)
        bars = conn.get_candles(symbol, "1d", from_date=from_d.isoformat(), to_date=to_d.isoformat())
        closes = [float(b.close) for b in bars][-250:]
        if len(closes) >= 2:
            return {"closes": closes, "bars_by_tf": {"1d": closes}}
    except Exception:  # noqa: BLE001 - candles are best-effort; fall back to the Yahoo cache
        pass
    return build_series_block(symbol)


def _directional_read(pred) -> tuple[str, float]:
    """Collapse the prediction into a single-stock BUY/SELL lean + directional conviction in [0,1].

    A directional structure (BULLISH/BEARISH) carries its calibrated conviction straight through; a
    non-directional read (range/vol/neutral) is turned into a directional lean from the risk-neutral
    P(above)/P(below) so every name gets a comparable conviction."""
    if pred.direction == BULLISH:
        return "bullish", float(pred.confidence)
    if pred.direction == BEARISH:
        return "bearish", float(pred.confidence)
    pa, pb = pred.prob_above, pred.prob_below
    if pa is None and pb is None:
        return "neutral", 0.0
    pa = float(pa) if pa is not None else (1.0 - float(pb))
    pb = float(pb) if pb is not None else (1.0 - pa)
    return ("bullish", pa) if pa >= pb else ("bearish", pb)


def predict_stock(conn, symbol: str, *, equity: float, source: str,
                  calibration=None, tip_metrics: dict | None = None, meta_label=None) -> dict:
    """Full-stack live prediction for ONE stock → a rich, JSON-able tip dict. Thread-safe: opens no
    DuckDB (``validation_store=None``); tier/edge are attached by the caller from the pooled cell."""
    chain = attach_parity_forward(conn.get_chain(symbol))
    series = _stock_series(conn, symbol)
    ctx, bucket, signals, pred, _tips = predict_for_chain(
        chain, source=source, equity=equity, validation_store=None,
        tip_metrics=tip_metrics, calibration=calibration, meta_label=meta_label, series=series)

    side, conviction = _directional_read(pred)
    spot = float(ctx.spot or 0.0)
    bullish = side == "bullish"
    target = round(spot * (1 + _TARGET_PCT) if bullish else spot * (1 - _TARGET_PCT), 2)
    stop = round(spot * (1 - _STOP_PCT) if bullish else spot * (1 + _STOP_PCT), 2)
    fired = [f for f in pred.factors if f.get("active")]
    momentum = ctx.momentum.to_dict() if getattr(ctx, "momentum", None) is not None else None
    return {
        "underlying": symbol.upper(),
        "direction": side,
        "conviction": round(conviction, 4),
        "calibrated_confidence": pred.calibrated_confidence,
        "signed": round(conviction if bullish else -conviction, 4),
        "tier": "watchlist",  # set from the pooled EQUITY cell by the caller
        "edge_verified": False,
        "target": target if side != "neutral" else None,
        "stop": stop if side != "neutral" else None,
        "horizon_days": float(_HORIZON),
        "spot": spot,
        "regime_bucket": bucket,
        "expected_move": pred.expected_move,
        "prob_above": pred.prob_above,
        "factors": fired,
        "n_factors_fired": len(fired),
        "momentum": momentum,
        "summary": pred.summary,
        "as_of": pred.as_of or chain.timestamp or "",
        "source": source,
    }


def rank_universe_live(symbols, *, conn, equity: float | None = None, source: str = "tip_live",
                       calibration=None, tip_metrics: dict | None = None, meta_label=None,
                       validation_store=None, concurrency: int | None = None) -> dict:
    """Deep-analyse ``symbols`` concurrently and rank into cross-sectional BUY/SELL.

    Returns ``{buys, sells, errors, as_of}`` with the SAME row shape the equities UI expects
    (underlying/direction/conviction/tier/target/stop/horizon_days) plus the rich factor breakdown."""
    equity = equity if equity is not None else SETTINGS.paper_starting_capital
    workers = max(1, concurrency or SETTINGS.stock_refresh_concurrency)
    syms = [s.upper() for s in symbols]

    results: list[dict] = []
    errors: list[dict] = []

    def _one(sym: str):
        try:
            return predict_stock(conn, sym, equity=equity, source=source,
                                 calibration=calibration, tip_metrics=tip_metrics, meta_label=meta_label)
        except Exception as e:  # noqa: BLE001 - one bad/illiquid name must not sink the feed
            return {"_error": {"symbol": sym, "error": (str(e) or type(e).__name__)[:200]}}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for r in pool.map(_one, syms):
            if r is None:
                continue
            if "_error" in r:
                errors.append(r["_error"])
            else:
                results.append(r)

    # Edge/tier verdict (single-threaded DuckDB read): the pooled EQUITY cell gates the headline tier,
    # exactly like the EOD equities engine (tips.equities._equity_tier).
    headline_ok = False
    if validation_store is not None:
        try:
            rep = validation_store.get(EQUITY_STRUCTURE, EQUITY_BUCKET, EQUITY_POOL)
            headline_ok = bool(rep and rep.get("headline_eligible"))
        except Exception:  # noqa: BLE001
            headline_ok = False
    for r in results:
        if headline_ok and (r["conviction"] or 0) > 0:
            r["tier"], r["edge_verified"] = "headline", True

    buys = sorted((r for r in results if r["direction"] == "bullish"),
                  key=lambda r: -(r["conviction"] or 0))
    sells = sorted((r for r in results if r["direction"] == "bearish"),
                   key=lambda r: -(r["conviction"] or 0))
    as_of = max((r.get("as_of") or "" for r in results), default="")
    return {"buys": buys, "sells": sells, "errors": errors, "as_of": as_of}
