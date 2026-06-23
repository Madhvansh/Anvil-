"""Implied-volatility round-trip: implied_vol(price(sigma)) == sigma."""

from __future__ import annotations

import pytest

from oip.quant import black76

pytestmark = [pytest.mark.validation]

_CASES = [
    ("c", 22000.0, 22000.0, 30 / 365, 0.065),
    ("p", 22000.0, 22000.0, 30 / 365, 0.065),
    ("c", 22000.0, 22500.0, 7 / 365, 0.065),
    ("p", 22000.0, 21500.0, 7 / 365, 0.065),
    ("c", 48000.0, 48000.0, 14 / 365, 0.065),
]


@pytest.mark.parametrize("flag,F,K,t,r", _CASES)
@pytest.mark.parametrize("sigma_true", [0.08, 0.14, 0.22, 0.35])
def test_iv_round_trip(flag, F, K, t, r, sigma_true):
    price = black76.price(flag, F, K, t, r, sigma_true)
    sigma_hat = black76.implied_vol(flag, price, F, K, t, r)
    assert sigma_hat == pytest.approx(sigma_true, rel=1e-5, abs=1e-6)
