"""The always-on prediction layer — turns one chain into a single best ``Prediction`` per underlying
so the live feed is NEVER empty, even when nothing is tradeable and no headline exists.

It wraps the shared ``tips_for_chain`` pipeline (so it can never drift from how tips are built), then
collapses the engine's read into one honest call:

  * if a TRADE tip exists → use its calibrated ``conviction`` and direction (prefer the HEADLINE one);
  * else if a candidate sizes (NO_TRADE) → use the top-ranked candidate's lean + conviction;
  * else → fall back to the pure risk-neutral directional probability (P above/below spot).

``confidence`` is therefore always a documented, calibratable number — never an asserted win-rate.
``edge_verified`` is read from the SAME validation store the gate uses, so the ✓ badge is earned only
on measured, post-cost, out-of-sample edge. Pure except the optional validation-store read.
"""

from __future__ import annotations

from ..config import SETTINGS
from ..strategy import generate_candidates
from ..strategy.types import BEARISH, BULLISH, LONG_VOL, NEUTRAL, SHORT_VOL
from .pipeline import tips_for_chain
from .types import HEADLINE, Prediction

_LEAN = {
    BULLISH: "bullish",
    BEARISH: "bearish",
    NEUTRAL: "range-bound",
    LONG_VOL: "expecting volatility to expand",
    SHORT_VOL: "expecting volatility to compress",
}


def _direction_from_rnd(prob_above: float | None) -> tuple[str, str]:
    """Directional lean + basis from the risk-neutral P(close > spot). Thresholds mirror the
    ``directional_drift`` factor (default 0.54 / 0.46, now config-backed) so prediction and factor
    agree; the defaults reproduce the previous constants exactly."""
    if prob_above is None:
        return NEUTRAL, "uninformative"
    if prob_above >= SETTINGS.rnd_directional_hi:
        return BULLISH, "rnd_directional"
    if prob_above <= SETTINGS.rnd_directional_lo:
        return BEARISH, "rnd_directional"
    return NEUTRAL, "rnd_neutral_band"


def _calibration_reference(confidence: float, tip_metrics: dict | None) -> dict | None:
    """Nearest LIVE reliability bin to ``confidence`` — so the UI can show, measured, how often a
    stated confidence near this level has actually landed. Read-only over the ledger metrics."""
    if not tip_metrics:
        return None
    live = tip_metrics.get("tip_live") or {}
    curve = live.get("reliability_curve") or []
    best = None
    for b in curve:
        pm = b.get("predicted_mean")
        if pm is None:
            continue
        d = abs(float(pm) - confidence)
        if best is None or d < best[0]:
            best = (d, b)
    return best[1] if best else None


def _risk_for_tip(best_tip, chain, equity: float):
    """Per-ticket risk distribution for the actionable tip (OWNER-only). Returns
    ``(risk_distribution, risk_of_ruin, forward_drawdown, roe_overlay)`` — the mc_pnl risk map
    (risk-neutral percentiles + VaR/CVaR, a risk map NOT a forecast), a repeated-bet ruin/drawdown MC,
    and the win/loss return-on-equity + breakeven overlay. Best-effort: any failure degrades to None so
    the prediction is never sunk by the risk overlay."""
    from ..engine.montecarlo import mc_pnl
    from .risk import legs_to_positions, modeled_returns, ruin_and_drawdown

    if best_tip is None:
        return None, None, None, None
    seed = int(best_tip.tip_id[:8], 16) if best_tip.tip_id else 0

    risk_distribution = None
    try:
        positions = legs_to_positions(best_tip.legs, best_tip.lot_size, chain.underlying, chain)
        mc = mc_pnl(chain, positions, horizon_days=float(best_tip.horizon_days or 7.0),
                    n_paths=4000, seed=seed)
        if mc.get("available"):
            risk_distribution = {
                "expected_pnl": mc["expected_pnl"], "p_profit": mc["p_profit"],
                "percentiles": mc["percentiles"], "var_95": mc["var_95"], "cvar_95": mc["cvar_95"],
                "caveat": mc["caveat"],
            }
    except Exception:  # noqa: BLE001 - the risk map is an overlay; never sink the prediction on it
        risk_distribution = None

    ror = None
    roe_overlay = None
    try:
        eq = float(equity or 0.0)
        ml = float(best_tip.max_loss or 0.0)
        if eq > 0 and ml > 0:
            mp = float(best_tip.max_profit) if best_tip.max_profit is not None else None
            cost = float(best_tip.round_trip_cost or 0.0)
            gross_win = mp if (mp is not None and mp > 0) else 1.5 * ml
            win_ret = max(0.0, gross_win - cost) / eq
            loss_ret = -(ml + cost) / eq
            p = float(best_tip.conviction or 0.5)
            ror = ruin_and_drawdown(modeled_returns(p, win_ret, loss_ret), seed=seed, basis="modeled")
            # Surface the win/loss ROE the ruin MC consumes internally + a breakeven-move read.
            spot = float(getattr(chain, "spot", 0.0) or 0.0)
            bes = [float(b) for b in (best_tip.breakevens or []) if b]
            be_move = round(min(abs(b - spot) for b in bes) / spot, 4) if (bes and spot > 0) else None
            roe_overlay = {
                "win_ret": round(win_ret, 4), "loss_ret": round(loss_ret, 4), "p_win": round(p, 4),
                "expected_roe": round(p * win_ret + (1.0 - p) * loss_ret, 4),
                "breakeven_move_pct": be_move,
            }
    except Exception:  # noqa: BLE001
        ror = None
        roe_overlay = None

    rr = ror.get("risk_of_ruin") if ror else None
    fd = ror.get("forward_drawdown") if ror else None
    return risk_distribution, rr, fd, roe_overlay


def _summary(underlying: str, direction: str, confidence: float, bucket: str,
             actionable: bool, verified: bool) -> str:
    pct = round(confidence * 100)
    lean = _LEAN.get(direction, direction or "neutral")
    tag = "edge-verified ✓" if verified else ("actionable" if actionable else "developing signal")
    return f"{underlying}: {lean} bias at ~{pct}% confidence ({tag}; regime: {bucket})."


def predict_for_chain(
    chain,
    *,
    source: str,
    equity: float,
    validation_store=None,
    tip_metrics: dict | None = None,
    calibration=None,
    cal_source_class: str = "tip_live",
    with_risk: bool = False,
    series: dict | None = None,
    meta_label=None,
):
    """Build the always-present ``Prediction`` for one chain. Returns
    ``(ctx, regime_bucket, signals, prediction, tips)`` — ``tips`` is the same gated list
    ``tips_for_chain`` produces (headline/watchlist), unchanged, for callers that still want it.

    The displayed ``confidence`` stays the RAW conviction; when a ``calibration`` service is supplied
    the calibrated value is attached ALONGSIDE as ``calibrated_confidence`` (never overwriting)."""
    ctx, bucket, signals, tips = tips_for_chain(
        chain, source=source, equity=equity, validation_store=validation_store, safe_sizing=True,
        series=series)

    spot = ctx.spot
    prob_above = ctx.prob_above(spot)
    prob_below = ctx.prob_below(spot)
    band = ctx.probability_band()

    headline_tip = next((t for t in tips if t.tier == HEADLINE), None)
    best_tip = headline_tip or (tips[0] if tips else None)

    actionable_tip = None
    if best_tip is not None:
        direction = best_tip.direction
        confidence = float(best_tip.conviction)
        basis = "candidate_conviction"
        best_structure = best_tip.structure
        has_actionable = True
        actionable_tip = best_tip.to_dict()
    else:
        # No tradeable candidate cleared the policy — still describe the engine's lean, then RND.
        cands = generate_candidates(ctx, equity, calibration=calibration,
                                    cal_source_class=cal_source_class)
        top = cands[0] if cands else None
        if top is not None and top.conviction and top.conviction > 0:
            direction = top.direction
            confidence = float(top.conviction)
            basis = "candidate_conviction"
            best_structure = top.strategy
        else:
            direction, basis = _direction_from_rnd(prob_above)
            if direction == BULLISH and prob_above is not None:
                confidence = float(prob_above)
            elif direction == BEARISH:
                confidence = float(prob_below) if prob_below is not None else (
                    1.0 - float(prob_above) if prob_above is not None else 0.5)
            else:  # range-bound: confidence the close stays within the ±1σ band
                pb = ctx.prob_between(band[0], band[1]) if band else None
                confidence = float(pb) if pb is not None else 0.5
            best_structure = top.strategy if top is not None else None
        has_actionable = False

    confidence = max(0.0, min(1.0, confidence))

    # Calibrated confidence shown ALONGSIDE the raw read (never replacing it). Only the
    # candidate-conviction basis has a "conviction" calibrator; RND-directional reads stay raw.
    calibrated_confidence = None
    if calibration is not None and basis == "candidate_conviction":
        try:
            if calibration.is_calibrated("conviction", cal_source_class):
                calibrated_confidence = round(
                    float(calibration.calibrate("conviction", confidence, source_class=cal_source_class)), 4)
        except Exception:  # noqa: BLE001 - display-only overlay; degrade to identity (raw confidence stands)
            calibrated_confidence = None

    # Meta-label ACT probability P(call correct) — Innovation I.4, DISPLAY-ONLY (never feeds the gate or
    # sizing). Injected (trained on resolved history by the caller); abstains (None) when not supplied.
    act_probability = None
    if meta_label is not None:
        try:
            from .meta_features import features_from

            fired = [s.name for s in signals if getattr(s, "active", False)]
            act = meta_label.predict(features_from(confidence, fired, bucket))
            act_probability = round(float(act), 4) if act is not None else None
        except Exception:  # noqa: BLE001 - the meta-label is an overlay; never sink the prediction
            act_probability = None

    edge_verified = False
    edge_basis = None
    if validation_store is not None and best_structure:
        rep = validation_store.get(best_structure, bucket, ctx.underlying)
        if rep:
            edge_verified = bool(rep.get("headline_eligible"))
            edge_basis = {
                "n": rep.get("n"),
                "win_rate": rep.get("win_rate"),
                "t_stat": rep.get("t_stat"),
                "dsr": rep.get("dsr"),
            }

    # Per-ticket risk distribution (OWNER-only; only when a tradeable tip exists). Serialized solely
    # via Prediction.to_dict(owner=True) behind the Phase-4 wall — so it is computed ONLY when the
    # caller will actually serve the owner view (``with_risk``). The MC (mc_pnl + ruin sim) is the
    # expensive bit; skipping it when the public surface would strip it anyway avoids wasted work in
    # production and keeps the test suite fast.
    risk_distribution = risk_of_ruin = forward_drawdown = roe_overlay = None
    if with_risk and has_actionable and best_tip is not None:
        risk_distribution, risk_of_ruin, forward_drawdown, roe_overlay = _risk_for_tip(best_tip, chain, equity)

    pred = Prediction(
        underlying=ctx.underlying,
        as_of=ctx.timestamp or "",
        spot=spot,
        direction=direction,
        confidence=round(confidence, 4),
        confidence_basis=basis,
        prob_above=prob_above,
        prob_below=prob_below,
        expected_move=ctx.expected_move,
        target_band=band,
        regime=getattr(ctx.regime, "label", ""),
        regime_bucket=bucket,
        factors=[s.to_dict() for s in signals],
        best_structure=best_structure,
        has_actionable_tip=has_actionable,
        edge_verified=edge_verified,
        edge_verified_basis=edge_basis,
        calibration_reference=_calibration_reference(confidence, tip_metrics),
        calibrated_confidence=calibrated_confidence,
        raw_confidence=round(confidence, 4),
        act_probability=act_probability,
        actionable_tip=actionable_tip,
        risk_distribution=risk_distribution,
        risk_of_ruin=risk_of_ruin,
        forward_drawdown=forward_drawdown,
        roe_overlay=roe_overlay,
        summary=_summary(ctx.underlying, direction, confidence, bucket, has_actionable, edge_verified),
    )
    return ctx, bucket, signals, pred, tips
