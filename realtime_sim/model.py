"""
Probabilistic direction model (transparent, fixed-prior, NOT fitted to recent data).

Why fixed priors instead of a trained ML model?  With a short live history, fitting
coefficients to recent prices is the fastest way to overfit and produce dishonest
confidence. Instead we blend a few *well-documented* effects with deliberately modest,
hand-set weights, CAP confidence, and let the tracker/backtest measure the TRUE reliability
empirically. Once enough resolved tips accrue, the tracker's isotonic recalibration (and,
later, a properly cross-validated ML meta-layer) can take over — gated by measured edge.

Signals (all standardized to ~unit scale so weights are comparable):
  * r5_z, r20_z   — time-series momentum (robust, documented), z-scored by realized vol
  * sma20_gap_z   — trend location vs the 20-day mean, in daily-vol units
  * rsi_meanrev   — mild mean-reversion penalty at RSI extremes (>70 / <30)
  * pcr_adj       — (indices only) small contrarian tilt from put/call OI ratio

Output: p_up in (0,1). Direction/abstention/target are decided in tips.py.
"""
from __future__ import annotations

import math

# Hand-set priors. Modest by design. Documented so they can be challenged & tuned.
_W_R5 = 0.80      # 5-day momentum — strongest at the daily/next-day horizon
_W_R20 = 0.40     # 20-day momentum — slower trend
_W_SMA = 0.50     # location vs 20d mean
_W_RSI = 0.50     # mean-reversion counterweight at extremes
_W_PCR = 0.30     # index positioning (small; PCR interpretation is debated)
_K = 0.80         # logistic slope (lower = humbler probabilities)


def _logistic(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _tanh(x: float) -> float:
    return math.tanh(x)


def _z(value: float, scale: float) -> float:
    return value / scale if scale > 1e-9 else 0.0


def direction_score(feats: dict, chain_feats: dict | None = None) -> dict:
    """Return {p_up, score, components} from candle (and optional chain) features."""
    vol20 = max(feats.get("vol20") or 0.0, 1e-4)
    r5_z = _z(feats["r5"], vol20 * math.sqrt(5))
    r20_z = _z(feats["r20"], vol20 * math.sqrt(20))
    sma_z = _z(feats["sma20_gap"], vol20)
    rsi = feats.get("rsi14")
    rsi_mr = 0.0
    if rsi is not None:
        if rsi > 70:
            rsi_mr = -(rsi - 70) / 30.0      # overbought → bearish nudge
        elif rsi < 30:
            rsi_mr = (30 - rsi) / 30.0        # oversold → bullish nudge

    score = (_W_R5 * _tanh(r5_z) + _W_R20 * _tanh(r20_z)
             + _W_SMA * _tanh(sma_z) + _W_RSI * rsi_mr)

    pcr_adj = 0.0
    if chain_feats and chain_feats.get("ok") and chain_feats.get("pcr"):
        # High PCR (lots of puts) → mild contrarian bullish tilt, clamped.
        pcr_adj = max(-0.4, min(0.4, (chain_feats["pcr"] - 1.0))) * _W_PCR
        score += pcr_adj

    p_up = _logistic(_K * score)
    return {
        "p_up": p_up,
        "score": score,
        "components": {"r5_z": r5_z, "r20_z": r20_z, "sma20_gap_z": sma_z,
                       "rsi_meanrev": rsi_mr, "pcr_adj": pcr_adj},
    }
