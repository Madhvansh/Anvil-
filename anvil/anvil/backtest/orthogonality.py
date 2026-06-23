"""Signal-admission gate — the formal anti-overfit / anti-overconfidence discipline (pure-numpy).

The Innovation Engine adds many signal families. Naively stacking them OVERFITS (more configs tried →
the Deflated-Sharpe penalty is the backstop) and DOUBLE-COUNTS correlated evidence (e.g. two vol
signals that are really one), which manufactures false confidence. This module makes the admission of a
new signal a *measured* decision, on three axes:

1. **Decorrelation** — a candidate must not be largely explained by the signals already admitted
   (max pairwise |corr| below a cap AND a minimum residual-information fraction from a multivariate
   regression of the candidate on the incumbents). Gaussian mutual information quantifies the overlap.
2. **Incremental edge** — adding the candidate must improve out-of-fold edge by a margin (the caller
   supplies edge-with vs edge-without, both measured OOF by the LOCKED gate — never in-sample).
3. **Shrinkage** — every estimated edge is shrunk toward a prior by its sampling uncertainty, so a
   thin-sample signal cannot present an overconfident number.

This module is STATISTICS ONLY — it never touches ``validate_cells`` / ``gate0`` formulas and never
feeds calibration into the gate. It is the gatekeeper that decides whether a signal is even allowed to
*compete* in the certification battery.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


def _aligned(*series) -> list[np.ndarray] | None:
    """Cast to float arrays of equal length (truncating to the shortest); None if any < 2 points."""
    arrs = [np.asarray(s, dtype=float) for s in series]
    if not arrs:
        return None
    n = min(a.size for a in arrs)
    if n < 2:
        return None
    return [a[-n:] for a in arrs]


def pearson(a, b) -> float | None:
    """Pearson correlation in [-1, 1]; None on degenerate (constant) input."""
    al = _aligned(a, b)
    if al is None:
        return None
    x, y = al
    x = x - x.mean()
    y = y - y.mean()
    denom = float(np.sqrt(np.sum(x * x) * np.sum(y * y)))
    if denom == 0:
        return None
    return float(np.clip(np.sum(x * y) / denom, -1.0, 1.0))


def gaussian_mutual_information(a, b) -> float | None:
    """MI (nats) under a joint-Gaussian assumption: -0.5·ln(1-ρ²). 0 = independent, ∞ = identical."""
    rho = pearson(a, b)
    if rho is None:
        return None
    r2 = min(rho * rho, 1.0 - 1e-12)
    return float(-0.5 * np.log(1.0 - r2))


def residual_information_fraction(candidate, incumbents: list) -> float | None:
    """Fraction of the candidate's variance NOT explained by a linear combo of the incumbents.

    1.0 = fully orthogonal (all new information); 0.0 = perfectly redundant (a linear combination of
    signals already admitted). Computed as ``1 - R²`` of an OLS regression of candidate on incumbents
    (with intercept). None if inputs are too short or degenerate.
    """
    if not incumbents:
        return 1.0
    al = _aligned(candidate, *incumbents)
    if al is None:
        return None
    y = al[0]
    X = np.column_stack([np.ones(y.size)] + al[1:])
    yc_var = float(np.sum((y - y.mean()) ** 2))
    if yc_var == 0:
        return None
    # Least-squares fit; residual sum of squares → R².
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    rss = float(np.sum(resid ** 2))
    r2 = 1.0 - rss / yc_var
    return float(np.clip(1.0 - r2, 0.0, 1.0))


def max_abs_correlation(candidate, incumbents: list) -> float:
    """Largest |Pearson| between the candidate and any single incumbent (0.0 if none)."""
    best = 0.0
    for inc in incumbents:
        c = pearson(candidate, inc)
        if c is not None:
            best = max(best, abs(c))
    return float(best)


def shrink_toward_prior(estimate: float, n: int, *, prior: float = 0.0, prior_weight: float = 20.0) -> float:
    """Bayesian/James-Stein-style shrinkage: ``(n·estimate + k·prior) / (n + k)``.

    With few samples (n ≪ k) the estimate is pulled hard toward the prior (kills overconfidence); with
    abundant samples (n ≫ k) it barely moves. ``prior_weight`` k = the pseudo-count of prior belief.
    """
    n = max(0, int(n))
    if n + prior_weight <= 0:
        return float(prior)
    return float((n * estimate + prior_weight * prior) / (n + prior_weight))


@dataclass
class AdmissionVerdict:
    admit: bool
    reasons: list = field(default_factory=list)
    max_corr: float = 0.0
    residual_fraction: float | None = None
    incremental_edge: float | None = None
    shrunk_edge: float | None = None

    def to_dict(self) -> dict:
        return {
            "admit": self.admit,
            "reasons": self.reasons,
            "max_corr": self.max_corr,
            "residual_fraction": self.residual_fraction,
            "incremental_edge": self.incremental_edge,
            "shrunk_edge": self.shrunk_edge,
        }


def admit_signal(
    candidate_returns,
    incumbent_returns: list,
    *,
    edge_with: float | None = None,
    edge_without: float | None = None,
    n_samples: int = 0,
    max_corr: float = 0.7,
    min_residual_fraction: float = 0.3,
    min_incremental_edge: float = 0.0,
    edge_prior: float = 0.0,
    prior_weight: float = 20.0,
) -> AdmissionVerdict:
    """Decide whether a new signal may JOIN the certified set, on decorrelation + incremental edge.

    A signal is admitted only if ALL hold:
      • max |corr| with any incumbent < ``max_corr`` (not a near-duplicate), AND
      • residual-information fraction ≥ ``min_residual_fraction`` (carries genuinely new variance), AND
      • (if edge_with/without supplied) the *shrunk* incremental OOF edge > ``min_incremental_edge``.

    The incremental edge is shrunk toward ``edge_prior`` by ``n_samples`` so a thin-sample lift can't
    win. Returns an explainable verdict; the caller (``full_cert``) only certifies admitted signals.
    """
    reasons: list[str] = []
    mac = max_abs_correlation(candidate_returns, incumbent_returns)
    resid = residual_information_fraction(candidate_returns, incumbent_returns)

    decorrelated = mac < max_corr
    if not decorrelated:
        reasons.append(f"too_correlated(|corr|={mac:.2f}≥{max_corr})")
    informative = resid is not None and resid >= min_residual_fraction
    if resid is None:
        reasons.append("residual_fraction_undefined")
    elif not informative:
        reasons.append(f"redundant(residual={resid:.2f}<{min_residual_fraction})")

    shrunk = None
    edge_ok = True
    if edge_with is not None and edge_without is not None:
        incremental = float(edge_with - edge_without)
        shrunk = shrink_toward_prior(incremental, n_samples, prior=edge_prior, prior_weight=prior_weight)
        edge_ok = shrunk > min_incremental_edge
        if not edge_ok:
            reasons.append(f"no_incremental_edge(shrunk={shrunk:.4f}≤{min_incremental_edge})")
    else:
        incremental = None

    admit = bool(decorrelated and informative and edge_ok)
    if admit:
        reasons.append("admitted")
    return AdmissionVerdict(
        admit=admit,
        reasons=reasons,
        max_corr=mac,
        residual_fraction=resid,
        incremental_edge=incremental,
        shrunk_edge=shrunk,
    )
