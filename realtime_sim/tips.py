"""
Tip generation - turn live data + features + model into actionable, honest tips.

A Tip carries: direction (UP/DOWN/NEUTRAL), CALIBRATED confidence, entry price, target +
1-sigma band, horizon, a short rationale, and a full feature snapshot for later analysis.
NEUTRAL = "no edge, abstain" and is a first-class outcome. Confidence is recalibrated against
the measured track record (calibration.py), so we never show a number we can't stand behind.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta

import calibration
import config
from features import candle_features, chain_features
from model import direction_score

_IST = timezone(timedelta(hours=5, minutes=30))
MODEL_VERSION = "anvil-live-structural-1.0.0"


@dataclass
class Tip:
    tip_id: str
    created_ts: str
    asset_class: str          # "index" | "stock"
    symbol: str
    horizon: str              # "intraday" | "next_day"
    direction: str            # "UP" | "DOWN" | "NEUTRAL" (the model's lean)
    confidence: float         # CALIBRATED P(direction correct) - the number we stand behind
    raw_lean: float           # uncalibrated model confidence (before reliability recalibration)
    status: str               # "ACTIONABLE" | "WATCH" | "ABSTAIN"
    edge_verified: bool       # has measured edge cleared the bar? (currently False - honest)
    p_up: float               # raw model probability of an up move
    entry_price: float
    target: float | None
    band_low: float | None
    band_high: float | None
    expected_move_pct: float | None
    rationale: str
    model_version: str = MODEL_VERSION
    provenance: str = "upstox_live"
    features: dict = field(default_factory=dict)
    status_lifecycle: str = "open"
    instrument_key: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _mk_id(symbol: str, horizon: str, created_ts: str) -> str:
    return hashlib.sha1(f"{symbol}|{horizon}|{created_ts}".encode()).hexdigest()[:16]


def _decide(p_up: float) -> tuple[str, float]:
    """Map raw p_up -> (direction, confidence) with abstention + confidence cap."""
    if p_up > 0.5 + config.ABSTAIN_BAND:
        direction, conf = "UP", p_up
    elif p_up < 0.5 - config.ABSTAIN_BAND:
        direction, conf = "DOWN", 1.0 - p_up
    else:
        return "NEUTRAL", max(p_up, 1.0 - p_up)
    conf = min(conf, config.CONF_CAP)
    if conf < config.MIN_CONF_TO_TIP:
        return "NEUTRAL", conf
    return direction, conf


def _horizon_days(horizon: str) -> float:
    return 1.0 if config.HORIZONS[horizon]["trading_days"] >= 1 else 0.4


def _build(symbol, asset_class, instrument_key, entry, feats, chain_feats, horizon, created_ts) -> Tip:
    ds = direction_score(feats, chain_feats)
    p_up = ds["p_up"]
    direction, raw_conf = _decide(p_up)
    cal = calibration.assess(raw_conf)
    conf = cal["calibrated_confidence"]            # the number we stand behind
    status = "ABSTAIN" if direction == "NEUTRAL" else cal["status"]
    vol20 = max(feats.get("vol20") or 0.0, 1e-4)
    sigma_h = vol20 * math.sqrt(_horizon_days(horizon))
    sign = 1 if direction == "UP" else (-1 if direction == "DOWN" else 0)
    target = entry * (1 + sign * 0.5 * sigma_h) if sign else None
    band_low, band_high = entry * (1 - sigma_h), entry * (1 + sigma_h)

    bits = [f"p_up={p_up:.2f}", f"r5={feats['r5']*100:+.1f}%", f"sma20_gap={feats['sma20_gap']*100:+.1f}%"]
    if feats.get("rsi14") is not None:
        bits.append(f"rsi={feats['rsi14']:.0f}")
    if chain_feats and chain_feats.get("ok"):
        bits.append(f"IV={chain_feats['atm_iv']*100:.1f}% PCR={chain_feats['pcr']:.2f}")
    rationale = ("ABSTAIN - directional edge below threshold; " if direction == "NEUTRAL"
                 else f"{direction} lean [{status}, edge_verified={cal['edge_verified']}] - ") + ", ".join(bits)

    return Tip(
        tip_id=_mk_id(symbol, horizon, created_ts), created_ts=created_ts,
        asset_class=asset_class, symbol=symbol, horizon=horizon,
        direction=direction, confidence=round(conf, 4), raw_lean=round(raw_conf, 4),
        status=status, edge_verified=bool(cal["edge_verified"]), p_up=round(p_up, 4),
        entry_price=round(entry, 2),
        target=round(target, 2) if target else None,
        band_low=round(band_low, 2), band_high=round(band_high, 2),
        expected_move_pct=round(sigma_h * 100, 3),
        rationale=rationale, instrument_key=instrument_key,
        features={**{k: feats[k] for k in feats if k != "ok"},
                  "chain": {k: chain_feats[k] for k in chain_feats if k != "ok"} if chain_feats and chain_feats.get("ok") else None},
    )


def generate_tips(client, *, indices=None, stocks=None, horizon=None) -> list:
    horizon = horizon or config.PRIMARY_HORIZON
    indices = config.INDICES if indices is None else indices
    stocks = config.stock_universe() if stocks is None else stocks
    created_ts = datetime.now(_IST).isoformat(timespec="seconds")
    tips = []

    for name in indices:
        try:
            ik = config.INDEX_INSTRUMENT_KEYS[name]
            chain = client.option_chain(name)
            cf = chain_features(name, chain, config.INDEX_TOUCH_STEP.get(name, 100.0))
            candles = client.daily_candles(ik, days=120)
            feats = candle_features(candles)
            if not feats.get("ok"):
                continue
            entry = cf["spot"] if cf.get("ok") else feats["last"]
            tips.append(_build(name, "index", ik, entry, feats, cf, horizon, created_ts))
        except Exception as e:
            print(f"  ! index {name} skipped: {type(e).__name__}: {str(e)[:120]}")

    for sym in stocks:
        try:
            ik = client.resolve_equity_key(sym)
            if not ik:
                print(f"  ! stock {sym} has no instrument key, skipped")
                continue
            candles = client.daily_candles(ik, days=120)
            feats = candle_features(candles)
            if not feats.get("ok"):
                continue
            entry = client.ltp(ik) or feats["last"]
            tips.append(_build(sym, "stock", ik, entry, feats, None, horizon, created_ts))
        except Exception as e:
            print(f"  ! stock {sym} skipped: {type(e).__name__}: {str(e)[:120]}")

    return tips
