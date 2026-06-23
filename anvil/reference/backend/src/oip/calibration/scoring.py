"""Calibration scoring — pure functions over (probability, binary-outcome) pairs.

All functions take an iterable of (prob, outcome) with prob in [0, 1] and outcome in {0, 1}, and
ignore malformed entries. Lower Brier / log-loss is better; the reliability diagram shows whether a
stated probability matches the observed frequency (the headline "when we say 70%, it happens ~70%").
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass


def _clean(pairs: Iterable[tuple[float, int]]) -> list[tuple[float, int]]:
    out = []
    for p, o in pairs:
        if p is None or o not in (0, 1):
            continue
        out.append((float(p), int(o)))
    return out


def brier_score(pairs: Iterable[tuple[float, int]]) -> float | None:
    """Mean squared error of probabilistic forecasts. 0 = perfect, 0.25 = always-50%, 1 = worst."""
    ps = _clean(pairs)
    if not ps:
        return None
    return sum((p - o) ** 2 for p, o in ps) / len(ps)


def log_loss(pairs: Iterable[tuple[float, int]], eps: float = 1e-15) -> float | None:
    ps = _clean(pairs)
    if not ps:
        return None
    total = 0.0
    for p, o in ps:
        pc = min(max(p, eps), 1 - eps)
        total += -(o * math.log(pc) + (1 - o) * math.log(1 - pc))
    return total / len(ps)


@dataclass
class ReliabilityBin:
    lo: float
    hi: float
    n: int
    mean_predicted: float | None
    observed_freq: float | None


def reliability_bins(pairs: Iterable[tuple[float, int]], n_bins: int = 10) -> list[ReliabilityBin]:
    """Bucket forecasts by predicted probability; compare mean predicted vs observed frequency."""
    ps = _clean(pairs)
    bins: list[ReliabilityBin] = []
    for b in range(n_bins):
        lo = b / n_bins
        hi = (b + 1) / n_bins
        # Last bin is closed on the right so p == 1.0 lands somewhere.
        in_bin = [
            (p, o) for p, o in ps if (lo <= p < hi or (b == n_bins - 1 and p == hi))
        ]
        if in_bin:
            mp = sum(p for p, _ in in_bin) / len(in_bin)
            of = sum(o for _, o in in_bin) / len(in_bin)
        else:
            mp = of = None
        bins.append(ReliabilityBin(lo=lo, hi=hi, n=len(in_bin), mean_predicted=mp, observed_freq=of))
    return bins


def coverage(intervals: Iterable[tuple[float, float, float]]) -> float | None:
    """Fraction of (lo, hi, realized) triples where lo <= realized <= hi.

    For an honestly-calibrated X% interval this should be ~X%.
    """
    items = [(lo, hi, x) for lo, hi, x in intervals if None not in (lo, hi, x)]
    if not items:
        return None
    inside = sum(1 for lo, hi, x in items if lo <= x <= hi)
    return inside / len(items)
