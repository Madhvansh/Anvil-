"""Finite-difference cross-checks — the core 'are the Greeks actually right' guard.

Each analytic Greek is compared to a central difference of the engine's `price` (whose path is
py_vollib when installed), so a wrong Greek formula fails regardless of how it was derived.
"""

from __future__ import annotations

import pytest

from oip.quant import black76

pytestmark = [pytest.mark.validation]

# (flag, F, K, t, r, sigma)
_CASES = [
    ("c", 22000.0, 22000.0, 30 / 365, 0.065, 0.14),
    ("p", 22000.0, 22000.0, 30 / 365, 0.065, 0.14),
    ("c", 22000.0, 22500.0, 7 / 365, 0.065, 0.18),
    ("p", 22000.0, 21500.0, 7 / 365, 0.065, 0.18),
    ("c", 48000.0, 48000.0, 14 / 365, 0.065, 0.20),
]


@pytest.mark.parametrize("flag,F,K,t,r,sigma", _CASES)
def test_delta_matches_finite_difference(flag, F, K, t, r, sigma):
    h = 1.0
    fd = (black76.price(flag, F + h, K, t, r, sigma) - black76.price(flag, F - h, K, t, r, sigma)) / (2 * h)
    assert black76.delta(flag, F, K, t, r, sigma) == pytest.approx(fd, rel=1e-4, abs=1e-7)


@pytest.mark.parametrize("flag,F,K,t,r,sigma", _CASES)
def test_gamma_matches_finite_difference(flag, F, K, t, r, sigma):
    h = 2.0
    fd = (
        black76.price(flag, F + h, K, t, r, sigma)
        - 2 * black76.price(flag, F, K, t, r, sigma)
        + black76.price(flag, F - h, K, t, r, sigma)
    ) / (h * h)
    assert black76.gamma(F, K, t, r, sigma) == pytest.approx(fd, rel=1e-3, abs=1e-9)


@pytest.mark.parametrize("flag,F,K,t,r,sigma", _CASES)
def test_vega_matches_finite_difference(flag, F, K, t, r, sigma):
    hs = 1e-4
    fd = (black76.price(flag, F, K, t, r, sigma + hs) - black76.price(flag, F, K, t, r, sigma - hs)) / (2 * hs)
    # Engine vega is RAW (per 1.0 vol); the finite difference is also per 1.0 vol.
    assert black76.vega(F, K, t, r, sigma) == pytest.approx(fd, rel=1e-5, abs=1e-4)


@pytest.mark.parametrize("flag,F,K,t,r,sigma", _CASES)
def test_theta_matches_finite_difference(flag, F, K, t, r, sigma):
    ht = 1e-6
    # Calendar theta per year = -dPrice/d(tau).
    fd = -(black76.price(flag, F, K, t + ht, r, sigma) - black76.price(flag, F, K, t - ht, r, sigma)) / (2 * ht)
    assert black76.theta(flag, F, K, t, r, sigma) == pytest.approx(fd, rel=1e-4, abs=1e-3)


@pytest.mark.parametrize("flag,F,K,t,r,sigma", _CASES)
def test_rho_matches_finite_difference_and_identity(flag, F, K, t, r, sigma):
    hr = 1e-6
    fd = (black76.price(flag, F, K, t, r + hr, sigma) - black76.price(flag, F, K, t, r - hr, sigma)) / (2 * hr)
    rho = black76.rho(flag, F, K, t, r, sigma)
    assert rho == pytest.approx(fd, rel=1e-5, abs=1e-3)
    # Under Black-76, r enters only via the discount factor → rho == -t * price exactly.
    assert rho == pytest.approx(-t * black76.price(flag, F, K, t, r, sigma), rel=1e-10, abs=1e-9)
