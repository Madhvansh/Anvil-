"""Decorrelated combination of per-target probabilities — never a naive agreement count.

The touch, VRP and credit-edge probabilities are all downstream of the SAME ``atm_iv`` (and the
shared ``total_gex`` / ``vrp_ratio``): touch runs the chain at ``atm_iv``; VRP's rich-probability is
``Φ((ln atm_iv − ln E[RV])/σ)``; every seller's edge is a ``1/vrp_ratio``-shifted read off the
``atm_iv``-derived RND. So counting "3 of 3 targets agree" would triple-count one vol shock and
over-state conviction → over-size → ruin.

The decorrelator is ZCA/Mahalanobis whitening of the shared feature matrix, with a Ledoit–Wolf
shrinkage of the covariance toward a scaled identity so it is well-conditioned on modest samples —
and a hard **no-op below ``min_n``** (with thin data the covariance is unreliable, so whitening would
inject noise). The supervised ``LogisticStacker`` is deferred: it needs JOINT multi-target resolved
labels that do not exist yet, and shipping it as the default would either overfit or force mixing
source classes.
"""

from __future__ import annotations

import numpy as np


def ledoit_wolf_cov(X) -> tuple[np.ndarray, float]:
    """Ledoit–Wolf shrinkage of the sample covariance toward ``μ·I`` (μ = mean eigenvalue). Returns
    ``(Σ_shrunk, delta)`` with the data-driven shrinkage intensity ``delta ∈ [0,1]``."""
    X = np.asarray(X, dtype=float)
    n, p = X.shape
    Xc = X - X.mean(axis=0, keepdims=True)
    S = (Xc.T @ Xc) / max(n, 1)
    mu = float(np.trace(S) / p)
    target = mu * np.eye(p)
    d2 = float(np.sum((S - target) ** 2) / p)
    if d2 <= 0.0:
        return S, 0.0
    b_bar2 = 0.0
    for i in range(n):
        xi = Xc[i:i + 1]
        Si = xi.T @ xi
        b_bar2 += float(np.sum((Si - S) ** 2) / p)
    b_bar2 /= max(n, 1) ** 2
    b2 = min(b_bar2, d2)
    delta = float(max(0.0, min(1.0, b2 / d2)))
    return (1.0 - delta) * S + delta * target, delta


def whiten_inputs(X, *, min_n: int = 50) -> tuple[np.ndarray, dict]:
    """ZCA-whiten the shared ``[atm_iv, total_gex, vrp_ratio]`` matrix using a Ledoit–Wolf covariance.
    **No-op below ``min_n``** (returns the centered-but-unwhitened matrix and ``applied=False``)."""
    X = np.asarray(X, dtype=float)
    if X.ndim != 2 or X.shape[0] < int(min_n):
        return X.copy(), {"applied": False, "n": int(X.shape[0]) if X.ndim == 2 else 0}
    mean = X.mean(axis=0)
    Xc = X - mean
    S, delta = ledoit_wolf_cov(X)
    vals, vecs = np.linalg.eigh(S)
    vals = np.clip(vals, 1e-12, None)
    W = vecs @ np.diag(1.0 / np.sqrt(vals)) @ vecs.T
    return Xc @ W, {"applied": True, "mean": mean.tolist(), "W": W.tolist(),
                    "delta": float(delta), "n": int(X.shape[0])}


def combine_calibrated(p_by_target: dict, weights: dict | None = None) -> float | None:
    """Combine per-target CALIBRATED probabilities into one number — a (decorrelated) weighted mean,
    NOT an agreement count. ``None`` per-target values are dropped; returns ``None`` if all missing."""
    present = {t: float(v) for t, v in p_by_target.items() if v is not None}
    if not present:
        return None
    if weights is None:
        w = {t: 1.0 for t in present}
    else:
        w = {t: float(weights.get(t, 0.0)) for t in present}
    total = sum(w.values()) or 1.0
    return float(sum(w[t] * present[t] for t in present) / total)


class LogisticStacker:
    """DEFERRED — a supervised logistic combiner over per-target ``logit(p̂)``. Needs joint
    multi-target resolved labels that don't exist yet; ``enabled`` is always False for now."""

    enabled = False

    def __init__(self):
        self.coef = None
        self.intercept = 0.0

    def predict(self, p_by_target: dict) -> float | None:  # pragma: no cover - deferred
        return combine_calibrated(p_by_target)
