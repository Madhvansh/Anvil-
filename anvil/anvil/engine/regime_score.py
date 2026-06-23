"""Regime read — trend / range / squeeze — as an AGREEMENT COUNT, never an "accuracy %" (C9).

There is no objective ground-truth regime label, so any "90% accurate" figure would require ex-post
look-ahead labelling — the exact false precision we refuse. Instead we run a transparent multi-signal
rules ensemble and report **how many of M signals agree** on the winning label, plus the firing
signals and their values. If regime ever makes a probabilistic claim, it gets calibrated like
everything else. Pure numpy over a daily close/return history + the live GEX sign + IV term shape.

Signals (each votes trend | range | squeeze | None):
  rv_trend   — short RV vs long RV (rising vol → squeeze; falling → range)
  drift      — |close − SMA20| / (RV·spot): a strong directional stretch → trend
  autocorr   — lag-1 autocorrelation of returns (momentum → trend; reversion → range)
  gex_sign   — dealer gamma: positive → range (mean-revert/pin); negative → trend (amplify)
  term_shape — IV backwardation → squeeze (event/stress); contango → range (calm)
  vol_of_vol — rising dispersion of rolling RV → squeeze (instability)
"""

from __future__ import annotations

import numpy as np

TREND, RANGE, SQUEEZE = "trend", "range", "squeeze"


def _rv(logret: np.ndarray) -> float:
    return float(np.std(logret, ddof=1) * np.sqrt(252)) if logret.size > 1 else 0.0


def regime_score(closes, *, gex_total: float | None = None, backwardation: bool | None = None) -> dict:
    """Return ``{label, agree_count, signals_total, signals:[{name, vote, value}]}`` — NO accuracy.
    ``closes`` is an ascending daily close series; ``gex_total``/``backwardation`` are the live reads."""
    c = np.asarray([x for x in (closes or []) if x and x == x], dtype=float)
    signals: list[dict] = []

    def vote(name, v, value):
        signals.append({"name": name, "vote": v, "value": value})

    if c.size >= 30:
        ret = np.diff(np.log(c))
        rv_short, rv_long = _rv(ret[-10:]), _rv(ret[-40:])
        ratio = rv_short / rv_long if rv_long > 0 else 1.0
        vote("rv_trend", SQUEEZE if ratio > 1.25 else RANGE if ratio < 0.8 else None, round(ratio, 3))

        sma20 = float(c[-20:].mean())
        stretch = (c[-1] - sma20) / (rv_long * c[-1]) if rv_long > 0 else 0.0
        vote("drift", TREND if abs(stretch) > 1.0 else RANGE if abs(stretch) < 0.3 else None, round(stretch, 3))

        a = ret[-40:]
        ac = float(np.corrcoef(a[:-1], a[1:])[0, 1]) if a.size > 3 else 0.0
        vote("autocorr", TREND if ac > 0.12 else RANGE if ac < -0.12 else None, round(ac, 3))

        roll = np.array([_rv(ret[i - 10:i]) for i in range(10, ret.size)])
        if roll.size > 6:
            vov = (roll[-5:].std() - roll[:-5].std())
            vote("vol_of_vol", SQUEEZE if vov > 0 and roll[-1] > roll.mean() else None, round(float(vov), 4))

    if gex_total is not None:
        vote("gex_sign", RANGE if gex_total > 0 else TREND, round(float(gex_total), 1))
    if backwardation is not None:
        vote("term_shape", SQUEEZE if backwardation else RANGE, bool(backwardation))

    votes = [s["vote"] for s in signals if s["vote"]]
    if not votes:
        return {"label": "neutral", "agree_count": 0, "signals_total": len(signals), "signals": signals}
    counts = {lbl: votes.count(lbl) for lbl in (TREND, RANGE, SQUEEZE)}
    label = max(counts, key=counts.get)
    return {"label": label, "agree_count": counts[label], "signals_total": len(signals),
            "signals": signals}
