"""Calibration scoring — Brier score, log-loss, reliability curve, coverage.

All operate on aligned arrays of predicted probabilities ``p`` (of a binary event) and
realized outcomes ``y`` in {0,1}. These are the standard, defensible calibration metrics;
none of them require the forecast to "predict price" — only to be honest about probability.
"""

from __future__ import annotations

import numpy as np


def brier_score(probs, events) -> float:
    """Mean squared error between predicted probability and realized {0,1}. Lower is better
    (0 = perfect; 0.25 = always saying 50%). The headline calibration number."""
    p = np.asarray(probs, dtype=float)
    y = np.asarray(events, dtype=float)
    if p.size == 0:
        return float("nan")
    return float(np.mean((p - y) ** 2))


def log_loss(probs, events, eps: float = 1e-12) -> float:
    p = np.clip(np.asarray(probs, dtype=float), eps, 1 - eps)
    y = np.asarray(events, dtype=float)
    if p.size == 0:
        return float("nan")
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def reliability_curve(probs, events, n_bins: int = 10) -> list[dict]:
    """Bin forecasts by predicted probability; compare mean predicted vs empirical frequency.

    A well-calibrated model has empirical_freq ≈ predicted_mean in every populated bin
    (points lie on the diagonal). Returns one dict per non-empty bin.
    """
    p = np.asarray(probs, dtype=float)
    y = np.asarray(events, dtype=float)
    out: list[dict] = []
    if p.size == 0:
        return out
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    for i in range(n_bins):
        lo, hi = edges[i], edges[i + 1]
        # last bin is inclusive of 1.0
        mask = (p >= lo) & (p < hi) if i < n_bins - 1 else (p >= lo) & (p <= hi)
        n = int(mask.sum())
        if n == 0:
            continue
        out.append(
            {
                "bin_low": float(lo),
                "bin_high": float(hi),
                "predicted_mean": float(p[mask].mean()),
                "empirical_freq": float(y[mask].mean()),
                "count": n,
            }
        )
    return out


def expected_calibration_error(probs, events, n_bins: int = 10) -> float:
    """ECE: count-weighted mean |empirical_freq − predicted_mean| across bins (0 = perfect)."""
    rows = reliability_curve(probs, events, n_bins)
    total = sum(r["count"] for r in rows)
    if not total:
        return float("nan")
    return float(sum(r["count"] * abs(r["empirical_freq"] - r["predicted_mean"]) for r in rows) / total)


def coverage(probs, events) -> dict:
    """For band forecasts: nominal (mean predicted prob the band contains the outcome) vs
    realized (fraction of times it did). |realized − nominal| small ⇒ honest bands.

    Returns None (not NaN) for empty input so the result is JSON-serializable."""
    p = np.asarray(probs, dtype=float)
    y = np.asarray(events, dtype=float)
    if p.size == 0:
        return {"nominal": None, "realized": None, "count": 0}
    return {"nominal": float(p.mean()), "realized": float(y.mean()), "count": int(p.size)}
