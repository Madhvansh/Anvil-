"""Probability-of-touch: the Brownian-bridge correction (C1) must reproduce the continuous
reflection-principle identity P(touch B) ≈ 2·P(terminal beyond B) for a driftless ATM-forward
barrier; P(touch) is monotone in horizon; the physical read is ≤/≥ the risk-neutral read exactly
as vrp_ratio ≶ 1 (C8); and the shared seeded ensemble is deterministic (C13)."""

from __future__ import annotations

import numpy as np
from scipy.stats import norm

from anvil.engine.touch_probability import touch_probabilities


def test_reflection_principle_atm_forward():
    # Zero arithmetic drift in log-space (r - q - 0.5σ² = 0) makes the reflection identity exact:
    # P(max X ≥ b) = 2·P(X_T ≥ b). Barrier set 0.5σ√T out → continuous P(terminal beyond) = N(-0.5).
    spot, sigma, h = 24000.0, 0.20, 20
    T = h / 252.0
    r, q = 0.5 * sigma * sigma, 0.0
    b_mult = 0.5
    K = spot * np.exp(b_mult * sigma * np.sqrt(T))
    res = touch_probabilities(spot, sigma, h, [K], r=r, q=q, vrp_ratio=1.0, n_paths=60000, seed=1)
    p_touch = res[float(K)]["p_touch_rn"]
    p_terminal = float(norm.cdf(-b_mult))  # ≈ 0.3085
    assert abs(p_touch - 2.0 * p_terminal) < 0.02, (p_touch, 2 * p_terminal)


def test_monotone_in_horizon():
    spot, sigma, K = 24000.0, 0.20, 24500.0
    ps = [touch_probabilities(spot, sigma, h, [K], vrp_ratio=1.0, n_paths=30000, seed=3)[K]["p_touch_rn"]
          for h in (3, 5, 10, 20)]
    assert all(ps[i] <= ps[i + 1] + 0.01 for i in range(len(ps) - 1)), ps


def test_physical_vs_rn_conditional_on_vrp_ratio():
    spot, sigma, K, h = 24000.0, 0.25, 24700.0, 12
    lo = touch_probabilities(spot, sigma, h, [K], vrp_ratio=0.8, n_paths=30000, seed=5)[K]
    assert lo["p_touch_phys"] <= lo["p_touch_rn"] + 1e-9    # lower vol → less likely to touch (C8)
    hi = touch_probabilities(spot, sigma, h, [K], vrp_ratio=1.2, n_paths=30000, seed=5)[K]
    assert hi["p_touch_phys"] >= hi["p_touch_rn"] - 1e-9    # higher vol → more likely (stress regime)


def test_deterministic_shared_ensemble():
    a = touch_probabilities(24000.0, 0.2, 10, [24500.0, 23500.0], vrp_ratio=0.9, seed=7)
    b = touch_probabilities(24000.0, 0.2, 10, [24500.0, 23500.0], vrp_ratio=0.9, seed=7)
    assert a == b and a[24500.0]["dir"] == "up" and a[23500.0]["dir"] == "down"
