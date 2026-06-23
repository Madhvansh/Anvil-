"""Edge cases and input guards: near-expiry intrinsic, delta bounds, and explicit raises."""

from __future__ import annotations

import math

import pytest

from oip.quant import black76

pytestmark = [pytest.mark.validation]


def test_near_expiry_call_approaches_intrinsic():
    F, K, r, sigma = 22000.0, 20000.0, 0.065, 0.15
    t = 1 / (365 * 24)  # ~1 hour to expiry
    df = math.exp(-r * t)
    intrinsic = (F - K) * df
    assert black76.price("c", F, K, t, r, sigma) == pytest.approx(intrinsic, rel=1e-3)


def test_deep_otm_call_approaches_zero():
    F, K, r, sigma = 22000.0, 30000.0, 0.065, 0.15
    t = 1 / (365 * 24)
    assert black76.price("c", F, K, t, r, sigma) == pytest.approx(0.0, abs=1e-6)


def test_delta_bounds():
    F, t, r, sigma = 22000.0, 30 / 365, 0.065, 0.15
    df = math.exp(-r * t)
    deep_itm_call = black76.delta("c", F, 15000.0, t, r, sigma)
    deep_otm_call = black76.delta("c", F, 30000.0, t, r, sigma)
    assert deep_itm_call == pytest.approx(df, abs=1e-3)   # call delta -> e^{-rt}
    assert deep_otm_call == pytest.approx(0.0, abs=1e-3)
    deep_itm_put = black76.delta("p", F, 30000.0, t, r, sigma)
    assert deep_itm_put == pytest.approx(-df, abs=1e-3)   # put delta -> -e^{-rt}


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sigma": 0.0},
        {"sigma": -0.1},
        {"t": 0.0},
        {"t": -0.01},
        {"F": 0.0},
        {"F": -100.0},
        {"K": 0.0},
        {"K": -100.0},
    ],
)
def test_invalid_inputs_raise(kwargs):
    base = {"F": 22000.0, "K": 22000.0, "t": 30 / 365, "r": 0.065, "sigma": 0.14}
    base.update(kwargs)
    with pytest.raises(ValueError):
        black76.price("c", base["F"], base["K"], base["t"], base["r"], base["sigma"])


@pytest.mark.parametrize("bad_r", [float("nan"), float("inf"), float("-inf"), -1.0, 2.0, 6.5])
def test_invalid_rate_raises(bad_r):
    # A NaN/inf or percent-vs-decimal r must fail fast, not silently misprice the chain.
    with pytest.raises(ValueError):
        black76.price("c", 22000.0, 22000.0, 30 / 365, bad_r, 0.14)


def test_option_type_accepts_enum_and_aliases():
    from oip.domain.enums import OptionType

    F, K, t, r, s = 22000.0, 22000.0, 30 / 365, 0.065, 0.14
    p_flag = black76.price("c", F, K, t, r, s)
    assert black76.price(OptionType.CALL, F, K, t, r, s) == pytest.approx(p_flag)
    assert black76.price("call", F, K, t, r, s) == pytest.approx(p_flag)
    assert black76.price("CE", F, K, t, r, s) == pytest.approx(p_flag)
