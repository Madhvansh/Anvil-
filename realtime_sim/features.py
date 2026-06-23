"""
Feature extraction (pure functions, unit-testable, stdlib-only).

Two families:
  * candle features  — momentum, trend, realized volatility, RSI (stocks AND index spot)
  * chain features   — ATM IV, expected move, PCR, OI walls, prob-of-touch (indices only)

Everything is computed from data available AT or BEFORE the decision timestamp, so the
same functions are safe to reuse in the walk-forward backtest (no look-ahead).
"""
from __future__ import annotations

import math
from datetime import datetime, timezone, timedelta

_IST = timezone(timedelta(hours=5, minutes=30))


# --- candle features --------------------------------------------------------
def _returns(closes: list[float]) -> list[float]:
    return [(closes[i] / closes[i - 1] - 1.0) for i in range(1, len(closes)) if closes[i - 1]]


def realized_vol(closes: list[float], window: int = 20) -> float:
    """Daily realized volatility (std of daily log returns) over the last `window`."""
    rets = _returns(closes[-(window + 1):])
    if len(rets) < 2:
        return 0.0
    m = sum(rets) / len(rets)
    var = sum((r - m) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var)


def sma(closes: list[float], n: int) -> float | None:
    return sum(closes[-n:]) / n if len(closes) >= n else None


def rsi(closes: list[float], n: int = 14) -> float | None:
    if len(closes) < n + 1:
        return None
    gains, losses = [], []
    for i in range(-n, 0):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    ag, al = sum(gains) / n, sum(losses) / n
    if al == 0:
        return 100.0
    rs = ag / al
    return 100.0 - 100.0 / (1.0 + rs)


def candle_features(candles: list[dict]) -> dict:
    """Momentum/trend/vol features from oldest→newest daily candles."""
    closes = [c["c"] for c in candles]
    if len(closes) < 25:
        return {"ok": False}
    last = closes[-1]
    sma20, sma50 = sma(closes, 20), sma(closes, 50)
    feats = {
        "ok": True,
        "last": last,
        "r1": closes[-1] / closes[-2] - 1.0,
        "r5": closes[-1] / closes[-6] - 1.0,
        "r10": closes[-1] / closes[-11] - 1.0,
        "r20": closes[-1] / closes[-21] - 1.0,
        "sma20_gap": (last / sma20 - 1.0) if sma20 else 0.0,
        "sma50_gap": (last / sma50 - 1.0) if sma50 else 0.0,
        "vol20": realized_vol(closes, 20),
        "rsi14": rsi(closes, 14),
    }
    return feats


# --- option-chain features (indices) ---------------------------------------
def year_fraction(expiry_iso: str, now: datetime | None = None) -> float:
    now = now or datetime.now(_IST)
    exp = datetime.fromisoformat(expiry_iso).replace(hour=15, minute=30, tzinfo=_IST)
    return max((exp - now).total_seconds() / (365.0 * 24 * 3600), 1e-6)


def prob_touch(spot: float, level: float, iv: float, t: float, vrp: float = 0.85) -> float:
    """Reflection-principle barrier approx, VRP-discounted; P(touch level before expiry)."""
    sigma = max(iv * vrp, 1e-6) * math.sqrt(t)
    if sigma <= 0 or spot <= 0 or level <= 0:
        return 0.0
    d = abs(math.log(level / spot)) / sigma
    return max(0.0, min(1.0, 2.0 * (0.5 * math.erfc(d / math.sqrt(2)))))


def chain_features(underlying: str, chain: dict, touch_step: float) -> dict:
    """ATM IV, expected move, PCR, OI walls, prob-of-touch from a live index chain."""
    rows = chain["rows"]
    if not rows:
        return {"ok": False}
    spot = float(rows[0].get("underlying_spot_price") or 0.0)
    atm = min(rows, key=lambda x: abs(float(x["strike_price"]) - spot))

    def leg(node, side):
        o = node.get(side) or {}
        return (o.get("market_data") or {}), (o.get("option_greeks") or {})

    ce_md, ce_gk = leg(atm, "call_options")
    pe_md, pe_gk = leg(atm, "put_options")
    ivs = [float(g["iv"]) / 100.0 for g in (ce_gk, pe_gk) if g.get("iv")]
    atm_iv = sum(ivs) / len(ivs) if ivs else 0.0
    straddle = float(ce_md.get("ltp") or 0) + float(pe_md.get("ltp") or 0)
    t = year_fraction(chain["expiry"])
    em_iv = spot * atm_iv * math.sqrt(t)

    call_oi = sum(float((n.get("call_options") or {}).get("market_data", {}).get("oi") or 0) for n in rows)
    put_oi = sum(float((n.get("put_options") or {}).get("market_data", {}).get("oi") or 0) for n in rows)
    pcr = (put_oi / call_oi) if call_oi else None
    call_wall = max(rows, key=lambda n: float((n.get("call_options") or {}).get("market_data", {}).get("oi") or 0))
    put_wall = max(rows, key=lambda n: float((n.get("put_options") or {}).get("market_data", {}).get("oi") or 0))

    up_level = math.ceil((spot + 0.5 * touch_step) / touch_step) * touch_step
    dn_level = math.floor((spot - 0.5 * touch_step) / touch_step) * touch_step

    return {
        "ok": True,
        "spot": spot,
        "expiry": chain["expiry"],
        "days_to_expiry": round(t * 365, 2),
        "atm_strike": float(atm["strike_price"]),
        "atm_iv": atm_iv,
        "straddle": straddle,
        "expected_move_iv": em_iv,
        "expected_move_straddle": 0.85 * straddle,
        "pcr": pcr,
        "call_wall": float(call_wall["strike_price"]),
        "put_wall": float(put_wall["strike_price"]),
        "p_touch_up": prob_touch(spot, up_level, atm_iv, t),
        "p_touch_down": prob_touch(spot, dn_level, atm_iv, t),
        "up_level": up_level,
        "dn_level": dn_level,
    }
