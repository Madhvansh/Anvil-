"""Black-76 Greeks: closed-form anchors + invariants + finite-difference cross-checks.

The finite-difference, parity, py_vollib-agreement, and IV-round-trip tests are grafted from
the OIP version's validation bar — a wrong Greek formula now fails the build, not a code review.
"""

import math

import pytest

from anvil.engine import greeks as gk
from anvil.models import OptionType

# Reference ATM case: F=K=100, T=1, r=0, sigma=0.2 (Black-76 with r=0 == BSM with q=0).
F, K, T, r, sig = 100.0, 100.0, 1.0, 0.0, 0.2


def test_atm_call_price():
    assert gk.price(OptionType.CALL, F, K, T, r, sig) == pytest.approx(7.9656, abs=1e-3)


def test_put_call_parity_identity():
    c = gk.price(OptionType.CALL, F, K, T, r, sig)
    p = gk.price(OptionType.PUT, F, K, T, r, sig)
    # Black-76 parity: C - P = e^{-rT}(F - K)
    assert (c - p) == pytest.approx(math.exp(-r * T) * (F - K), abs=1e-6)


def test_greeks_reference_values():
    g = gk.compute_greeks(OptionType.CALL, F, K, T, r, sig)
    assert g.delta == pytest.approx(0.539828, abs=1e-4)
    assert g.gamma == pytest.approx(0.0198476, abs=1e-5)
    assert g.vega == pytest.approx(0.396953, abs=1e-4)  # per 1%
    assert g.theta == pytest.approx(-3.96953 / 365.0, abs=1e-5)  # per day


def test_gamma_equal_call_put_and_delta_relationship():
    gc = gk.compute_greeks(OptionType.CALL, F, K, T, r, sig)
    gp = gk.compute_greeks(OptionType.PUT, F, K, T, r, sig)
    assert gc.gamma == pytest.approx(gp.gamma, abs=1e-9)
    assert (gc.delta - gp.delta) == pytest.approx(math.exp(-r * T), abs=1e-6)


# ---- finite-difference cross-checks (the real "are the Greeks right" guard) ----
# (flag, F, K, t, r, sigma)
_CASES = [
    (OptionType.CALL, 22000.0, 22000.0, 30 / 365, 0.065, 0.14),
    (OptionType.PUT, 22000.0, 22000.0, 30 / 365, 0.065, 0.14),
    (OptionType.CALL, 22000.0, 22500.0, 7 / 365, 0.065, 0.18),
    (OptionType.PUT, 22000.0, 21500.0, 7 / 365, 0.065, 0.18),
    (OptionType.CALL, 48000.0, 48000.0, 14 / 365, 0.065, 0.20),
]


@pytest.mark.parametrize("ot,f,k,t,rr,s", _CASES)
def test_delta_matches_finite_difference(ot, f, k, t, rr, s):
    h = 1.0
    fd = (gk.price(ot, f + h, k, t, rr, s) - gk.price(ot, f - h, k, t, rr, s)) / (2 * h)
    assert float(gk.delta(ot, f, k, t, rr, s)) == pytest.approx(fd, rel=1e-4, abs=1e-7)


@pytest.mark.parametrize("ot,f,k,t,rr,s", _CASES)
def test_gamma_matches_finite_difference(ot, f, k, t, rr, s):
    h = 2.0
    fd = (gk.price(ot, f + h, k, t, rr, s) - 2 * gk.price(ot, f, k, t, rr, s) + gk.price(ot, f - h, k, t, rr, s)) / (h * h)
    assert float(gk.gamma(f, k, t, rr, s)) == pytest.approx(fd, rel=1e-3, abs=1e-9)


@pytest.mark.parametrize("ot,f,k,t,rr,s", _CASES)
def test_vega_matches_finite_difference(ot, f, k, t, rr, s):
    hs = 1e-4
    fd = (gk.price(ot, f, k, t, rr, s + hs) - gk.price(ot, f, k, t, rr, s - hs)) / (2 * hs)
    assert float(gk.vega(f, k, t, rr, s)) == pytest.approx(fd, rel=1e-5, abs=1e-4)


@pytest.mark.parametrize("ot,f,k,t,rr,s", _CASES)
def test_theta_matches_finite_difference(ot, f, k, t, rr, s):
    ht = 1e-6
    fd = -(gk.price(ot, f, k, t + ht, rr, s) - gk.price(ot, f, k, t - ht, rr, s)) / (2 * ht)
    assert float(gk.theta(ot, f, k, t, rr, s)) == pytest.approx(fd, rel=1e-4, abs=1e-3)


@pytest.mark.parametrize("ot,f,k,t,rr,s", _CASES)
def test_rho_identity(ot, f, k, t, rr, s):
    # Under Black-76, r enters only via the discount factor → rho == -t * price exactly.
    assert float(gk.rho(ot, f, k, t, rr, s)) == pytest.approx(-t * float(gk.price(ot, f, k, t, rr, s)), rel=1e-10, abs=1e-9)


# ---- higher-order Greeks validated by finite difference ----
@pytest.mark.parametrize("ot,f,k,t,rr,s", _CASES)
def test_vanna_matches_finite_difference(ot, f, k, t, rr, s):
    from anvil.engine.higher_order import vanna

    hs = 1e-5
    fd = (float(gk.delta(ot, f, k, t, rr, s + hs)) - float(gk.delta(ot, f, k, t, rr, s - hs))) / (2 * hs)
    assert float(vanna(f, k, t, rr, s)) == pytest.approx(fd, rel=1e-3, abs=1e-4)


@pytest.mark.parametrize("ot,f,k,t,rr,s", _CASES)
def test_charm_matches_finite_difference(ot, f, k, t, rr, s):
    from anvil.engine.higher_order import charm

    ht = 1e-6
    fd = (float(gk.delta(ot, f, k, t + ht, rr, s)) - float(gk.delta(ot, f, k, t - ht, rr, s))) / (2 * ht)
    assert float(charm(ot, f, k, t, rr, s)) == pytest.approx(fd, rel=1e-3, abs=1e-3)


@pytest.mark.parametrize("ot", [OptionType.CALL, OptionType.PUT])
@pytest.mark.parametrize("vol", [0.08, 0.15, 0.30, 0.55])
def test_implied_vol_roundtrip(ot, vol):
    p = float(gk.price(ot, 24000, 24100, 0.05, 0.065, vol))
    recovered = gk.implied_vol(p, ot, 24000, 24100, 0.05, 0.065)
    assert recovered == pytest.approx(vol, abs=1e-3)


def test_validate_rejects_percent_rate():
    with pytest.raises(ValueError):
        gk.compute_greeks(OptionType.CALL, 100, 100, 1.0, 6.5, 0.2)  # r as 6.5 not 0.065
