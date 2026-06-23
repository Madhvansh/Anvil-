"""Multi-timeframe momentum engine — pure-numpy, pandas-free.

The momentum read Anvil was missing: **time-series (absolute) and cross-sectional momentum across
every relevant horizon** (minutes → hours → days → weeks) for index *and* single stocks, plus the
classic intraday mechanics (opening-range, VWAP, gap) and the Baltussen et al. (JFE 2021) last-30-min
expiry-day gamma drift.

Honesty rails (mirrors ``engine.regime_score``): momentum is reported as a **vol-normalized trend
score + an agreement count across timeframes**, NEVER as an accuracy %. Every function **abstains**
(returns ``None`` / ``fired=False``) on insufficient history rather than guessing. Thresholds live in
the callers/factors (config-backed) so the GATE certifies them, not this module.

All inputs are plain ascending series (oldest → newest). No I/O, no chain dependency — so the same
primitives serve EOD closes, intraday bars, and recorded option-flow series alike.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# Direction tags — string-identical to ``anvil.strategy.types`` (the engine tier stays free of any
# strategy dependency; FactorSignal.direction is just a string, so these interoperate directly).
NEUTRAL = "neutral"
BULLISH = "bullish"
BEARISH = "bearish"


# --------------------------------------------------------------------------- #
# Primitives (each hand-verifiable; NaN-safe; abstain on short series).
# --------------------------------------------------------------------------- #
def _clean(series) -> np.ndarray:
    """Ascending float array with NaNs dropped (``x == x`` is False only for NaN)."""
    a = np.asarray(series, dtype=float)
    return a[a == a]


def roc(series, n: int) -> float | None:
    """Rate of change over ``n`` steps: ``c[-1]/c[-1-n] - 1``. None if too short or base ≤ 0."""
    c = _clean(series)
    if c.size < n + 1:
        return None
    base = c[-1 - n]
    if base <= 0:
        return None
    return float(c[-1] / base - 1.0)


def sma(series, n: int) -> float | None:
    """Simple moving average of the last ``n`` points."""
    c = _clean(series)
    if c.size < n or n <= 0:
        return None
    return float(np.mean(c[-n:]))


def ema(series, span: int) -> float | None:
    """Exponential moving average (last value), span→alpha = 2/(span+1). Seeded with the first point."""
    c = _clean(series)
    if c.size == 0 or span <= 0:
        return None
    alpha = 2.0 / (span + 1.0)
    e = c[0]
    for x in c[1:]:
        e = alpha * x + (1.0 - alpha) * e
    return float(e)


def _wilder(values: np.ndarray, n: int) -> np.ndarray:
    """Wilder's smoothing (RMA) — the standard for RSI/ADX. Returns the smoothed series."""
    out = np.empty(values.size, dtype=float)
    out[:] = np.nan
    if values.size < n:
        return out
    seed = float(np.mean(values[:n]))
    out[n - 1] = seed
    prev = seed
    for i in range(n, values.size):
        prev = (prev * (n - 1) + values[i]) / n
        out[i] = prev
    return out


def rsi(series, n: int = 14) -> float | None:
    """Wilder RSI in [0, 100]. All-gains → 100, all-losses → 0, flat → 50. Needs ≥ n+1 points."""
    c = _clean(series)
    if c.size < n + 1:
        return None
    d = np.diff(c)
    gains = np.where(d > 0, d, 0.0)
    losses = np.where(d < 0, -d, 0.0)
    avg_gain = _wilder(gains, n)[-1]
    avg_loss = _wilder(losses, n)[-1]
    if not (avg_gain == avg_gain and avg_loss == avg_loss):  # NaN guard
        return None
    if avg_loss == 0.0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return float(100.0 - 100.0 / (1.0 + rs))


def true_range(high, low, close) -> np.ndarray | None:
    """True range series (length = len-1): max(h-l, |h-prev_c|, |l-prev_c|)."""
    h, lo, c = np.asarray(high, float), np.asarray(low, float), np.asarray(close, float)
    if not (h.size == lo.size == c.size) or c.size < 2:
        return None
    hl = h[1:] - lo[1:]
    hc = np.abs(h[1:] - c[:-1])
    lc = np.abs(lo[1:] - c[:-1])
    return np.maximum.reduce([hl, hc, lc])


def atr(high, low, close, n: int = 14) -> float | None:
    """Average true range (Wilder) — the volatility unit for normalizing intraday moves."""
    tr = true_range(high, low, close)
    if tr is None or tr.size < n:
        return None
    return float(_wilder(tr, n)[-1])


def adx(high, low, close, n: int = 14) -> float | None:
    """Average Directional Index in [0, 100] — TREND STRENGTH (not direction). Needs ≥ 2n+1 bars.

    High ADX (>~25) = strong trend (momentum regime); low ADX (<~20) = chop (mean-revert regime).
    """
    h, lo, c = np.asarray(high, float), np.asarray(low, float), np.asarray(close, float)
    if not (h.size == lo.size == c.size) or c.size < 2 * n + 1:
        return None
    up = h[1:] - h[:-1]
    dn = lo[:-1] - lo[1:]
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = true_range(h, lo, c)
    atr_s = _wilder(tr, n)
    plus_di = 100.0 * _wilder(plus_dm, n) / atr_s
    minus_di = 100.0 * _wilder(minus_dm, n) / atr_s
    denom = plus_di + minus_di
    dx = 100.0 * np.abs(plus_di - minus_di) / np.where(denom == 0, np.nan, denom)
    dx_valid = dx[dx == dx]
    if dx_valid.size < n:
        return None
    return float(np.mean(dx_valid[-n:]))


def donchian(high, low, n: int) -> dict | None:
    """Donchian channel over the last ``n`` bars: {upper, lower, mid}. The breakout reference."""
    h, lo = np.asarray(high, float), np.asarray(low, float)
    if h.size < n or lo.size < n or n <= 0:
        return None
    upper, lower = float(np.max(h[-n:])), float(np.min(lo[-n:]))
    return {"upper": upper, "lower": lower, "mid": (upper + lower) / 2.0}


def vwap(prices, volumes) -> float | None:
    """Volume-weighted average price. None if no volume."""
    p, v = np.asarray(prices, float), np.asarray(volumes, float)
    if p.size == 0 or p.size != v.size:
        return None
    tot = float(np.sum(v))
    if tot <= 0:
        return None
    return float(np.sum(p * v) / tot)


def opening_range(highs, lows, first_n: int = 3) -> dict | None:
    """Opening-range high/low from the first ``first_n`` intraday bars."""
    h, lo = np.asarray(highs, float), np.asarray(lows, float)
    if h.size < first_n or lo.size < first_n or first_n <= 0:
        return None
    return {"or_high": float(np.max(h[:first_n])), "or_low": float(np.min(lo[:first_n]))}


def gap_pct(prev_close: float, today_open: float) -> float | None:
    """Overnight gap as a fraction of the prior close."""
    if prev_close is None or today_open is None or prev_close <= 0:
        return None
    return float(today_open / prev_close - 1.0)


def autocorr(returns, lag: int = 1) -> float | None:
    """Lag-k autocorrelation of a return series in [-1, 1]. Positive → trending; negative → reverting."""
    r = _clean(returns)
    if r.size < lag + 2:
        return None
    a, b = r[:-lag], r[lag:]
    a = a - a.mean()
    b = b - b.mean()
    denom = np.sqrt(np.sum(a * a) * np.sum(b * b))
    if denom == 0:
        return None
    return float(np.sum(a * b) / denom)


# --------------------------------------------------------------------------- #
# Time-series (absolute) momentum across timeframes.
# --------------------------------------------------------------------------- #
def _vol_normalized_momentum(closes, lookback: int) -> float | None:
    """Trend score = (return over ``lookback``) / (vol of step returns over the same window).

    A unit-free, comparable-across-timeframes "trend Sharpe": >0 up-trend, <0 down-trend, magnitude =
    how clean the move is relative to its own noise. Returns None on insufficient/zero-vol history.
    """
    c = _clean(closes)
    if c.size < lookback + 1:
        return None
    seg = c[-(lookback + 1):]
    if seg[0] <= 0:
        return None
    rets = np.diff(np.log(seg))
    sd = float(np.std(rets, ddof=1)) if rets.size > 1 else 0.0
    total = float(np.log(seg[-1] / seg[0]))
    if sd <= 0:
        return None
    return total / (sd * np.sqrt(rets.size))


def time_series_momentum(closes, lookbacks=(5, 10, 21, 63)) -> dict | None:
    """Absolute (time-series) momentum at several lookbacks on ONE close series.

    Returns ``{lookback: {"roc": .., "score": vol_normalized}}`` for every lookback with enough data,
    or None if none qualify. ``score`` is comparable across lookbacks (vol-normalized).
    """
    c = _clean(closes)
    out: dict[int, dict] = {}
    for lb in lookbacks:
        r = roc(c, lb)
        s = _vol_normalized_momentum(c, lb)
        if r is None and s is None:
            continue
        out[int(lb)] = {"roc": r, "score": s}
    return out or None


@dataclass
class MomentumRead:
    """Consensus multi-timeframe momentum read — an agreement count, never an accuracy %."""

    direction: str = NEUTRAL          # BULLISH | BEARISH | NEUTRAL
    strength: float = 0.0             # 0..1 conviction weight (|net agreement| × clean-trend factor)
    agreement: int = 0               # signed: #bullish-tf minus #bearish-tf
    n_timeframes: int = 0            # how many timeframes had enough data to vote
    per_tf: dict = field(default_factory=dict)  # tf-label → {"score","roc","vote"}
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "direction": self.direction,
            "strength": round(self.strength, 4),
            "agreement": self.agreement,
            "n_timeframes": self.n_timeframes,
            "per_tf": self.per_tf,
            "note": self.note,
        }


def multi_timeframe_momentum(
    series_by_tf: dict[str, list],
    *,
    score_threshold: float = 0.5,
    primary_lookback: int = 10,
) -> MomentumRead:
    """Fuse absolute momentum across timeframes into ONE consensus read.

    ``series_by_tf`` maps a timeframe label (e.g. "5m"/"1h"/"1d"/"1w") to its ascending close series.
    Each timeframe votes BULLISH/BEARISH/abstain by its vol-normalized trend score vs ``score_threshold``.
    The consensus direction needs a NET agreement (more tf's agree than disagree); strength scales with
    the net agreement fraction × the average clean-trend magnitude. Abstains (NEUTRAL, strength 0) when
    timeframes disagree or have no data — the honest default.
    """
    per_tf: dict[str, dict] = {}
    votes: list[int] = []
    mags: list[float] = []
    for label, series in series_by_tf.items():
        score = _vol_normalized_momentum(series, primary_lookback)
        r = roc(series, primary_lookback)
        if score is None:
            per_tf[label] = {"score": None, "roc": r, "vote": 0, "reason": "insufficient_history"}
            continue
        vote = 1 if score >= score_threshold else (-1 if score <= -score_threshold else 0)
        per_tf[label] = {"score": round(score, 4), "roc": r, "vote": vote}
        if vote != 0:
            votes.append(vote)
            mags.append(abs(score))

    n = len(votes)
    if n == 0:
        return MomentumRead(NEUTRAL, 0.0, 0, len(per_tf), per_tf, "no_timeframe_fired")
    agreement = int(sum(votes))
    if agreement == 0:
        return MomentumRead(NEUTRAL, 0.0, 0, len(per_tf), per_tf, "timeframes_conflict")
    direction = BULLISH if agreement > 0 else BEARISH
    # Net-agreement fraction (consensus cleanliness) × mean trend magnitude, capped to 1.
    net_frac = abs(agreement) / float(n)
    mag = float(np.tanh(np.mean(mags)))  # squashes the vol-normalized score into 0..1
    strength = round(min(1.0, net_frac * mag), 4)
    return MomentumRead(direction, strength, agreement, len(per_tf), per_tf, "consensus")


# --------------------------------------------------------------------------- #
# Cross-sectional (relative) momentum.
# --------------------------------------------------------------------------- #
def cross_sectional_rank(returns_by_symbol: dict[str, float]) -> dict[str, dict]:
    """Rank symbols by a momentum return into a [0, 1] percentile (1 = strongest, 0 = weakest).

    The cross-sectional anomaly engine: relative winners over a lookback tend to keep outperforming.
    Returns ``{symbol: {"return","percentile","rank"}}``; ties share the average percentile.
    """
    clean = {s: float(v) for s, v in returns_by_symbol.items() if v == v}
    if not clean:
        return {}
    syms = list(clean)
    vals = np.array([clean[s] for s in syms], dtype=float)
    order = vals.argsort()                       # ascending
    ranks = np.empty_like(order, dtype=float)
    ranks[order] = np.arange(vals.size, dtype=float)
    denom = max(1, vals.size - 1)
    out: dict[str, dict] = {}
    for i, s in enumerate(syms):
        out[s] = {
            "return": round(float(vals[i]), 6),
            "percentile": round(float(ranks[i] / denom), 4),
            "rank": int(vals.size - ranks[i]),  # 1 = strongest
        }
    return out


# --------------------------------------------------------------------------- #
# Intraday mechanics.
# --------------------------------------------------------------------------- #
def or_breakout(session_highs, session_lows, last_price: float, first_n: int = 3) -> dict | None:
    """Opening-range breakout read: is ``last_price`` above the OR-high (up) / below OR-low (down)?"""
    rng = opening_range(session_highs, session_lows, first_n)
    if rng is None or last_price is None:
        return None
    if last_price > rng["or_high"]:
        direction, fired = BULLISH, True
    elif last_price < rng["or_low"]:
        direction, fired = BEARISH, True
    else:
        direction, fired = NEUTRAL, False
    width = rng["or_high"] - rng["or_low"]
    dist = (last_price - rng["or_high"]) if direction == BULLISH else (rng["or_low"] - last_price)
    strength = round(min(1.0, dist / width), 4) if (fired and width > 0) else 0.0
    return {**rng, "direction": direction, "fired": fired, "strength": strength}


def vwap_reversion(prices, volumes, last_price: float) -> dict | None:
    """Distance of price from session VWAP, in fractional terms. Positive = above VWAP (extended up)."""
    vw = vwap(prices, volumes)
    if vw is None or last_price is None or vw <= 0:
        return None
    dist = float(last_price / vw - 1.0)
    return {"vwap": vw, "distance": dist, "above": dist > 0}


def last30_expiry_gamma_drift(
    intraday_returns, gex_sign: int, *, days_to_expiry: int = 0
) -> dict | None:
    """Baltussen et al. (JFE 2021): in a NEGATIVE dealer-gamma regime, hedging amplifies the day's
    move, so the late-session return tends to CONTINUE the rest-of-day return — strongest on/near
    expiry. Returns a directional drift read; ``fired`` only when gamma is negative and near expiry.

    INDIA-UNVALIDATED: the mechanism is SPX-evidenced; on Indian expiries large directional players can
    dominate (Jane Street). So this is research-grade — callers tier it CONFIRMATION until the live
    reliability curve + a cert cell back it.
    """
    r = _clean(intraday_returns)
    if r.size < 2:
        return None
    rest_of_day = float(np.sum(r[:-1]))
    negative_gamma = gex_sign < 0
    near_expiry = days_to_expiry <= 1
    fired = negative_gamma and near_expiry and abs(rest_of_day) > 0
    if not fired:
        direction = NEUTRAL
    else:
        direction = BULLISH if rest_of_day > 0 else BEARISH
    return {
        "direction": direction,
        "fired": fired,
        "rest_of_day_return": rest_of_day,
        "negative_gamma": negative_gamma,
        "days_to_expiry": days_to_expiry,
        "note": "india_unvalidated_research_grade",
    }
