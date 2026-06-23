"""Monte-Carlo robustness for a tip cell's per-trade returns.

A genuine edge survives perturbation of the trade sequence. We moving-block-bootstrap the per-trade
(post-cost) return series and report the 5th-percentile bootstrap mean: if even the unlucky 5% tail
of resamples is positive, the edge is robust to sequencing/luck. Block sampling preserves any
short-run autocorrelation. Deterministic given ``seed``.
"""

from __future__ import annotations

import numpy as np


def block_bootstrap_edge(returns, n_boot: int = 1000, block: int = 5, q: float = 0.05, seed: int = 0) -> dict:
    """Return {mean, p_low, n}: the observed mean per-trade return and the q-quantile of the
    bootstrap distribution of the mean. p_low > 0 ⇒ robust positive edge. NaN if < 2 trades."""
    r = np.asarray([x for x in returns if x == x], dtype=float)
    n = r.size
    if n < 2:
        return {"mean": float("nan"), "p_low": float("nan"), "n": int(n)}
    rng = np.random.default_rng(seed)
    block = max(1, min(int(block), n))
    n_blocks = int(np.ceil(n / block))
    starts_hi = n - block + 1
    means = np.empty(n_boot, dtype=float)
    for b in range(n_boot):
        starts = rng.integers(0, starts_hi, size=n_blocks)
        sample = np.concatenate([r[s:s + block] for s in starts])[:n]
        means[b] = sample.mean()
    return {"mean": float(r.mean()), "p_low": float(np.quantile(means, q)), "n": int(n)}
