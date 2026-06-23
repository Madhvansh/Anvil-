"""Put-call parity: C - P == e^{-rt} (F - K), implementation-agnostic across a grid.

This catches sign and discounting errors instantly without any external reference.
"""

from __future__ import annotations

import math

import pytest

from oip.quant import black76

pytestmark = [pytest.mark.validation]

_STRIKES = [21000.0, 21500.0, 22000.0, 22500.0, 23000.0]
_TENORS = [1 / 365, 7 / 365, 30 / 365]
_SIGMAS = [0.10, 0.14, 0.22]
_F = 22000.0
_R = 0.065


@pytest.mark.parametrize("K", _STRIKES)
@pytest.mark.parametrize("t", _TENORS)
@pytest.mark.parametrize("sigma", _SIGMAS)
def test_put_call_parity(K, t, sigma):
    c = black76.price("c", _F, K, t, _R, sigma)
    p = black76.price("p", _F, K, t, _R, sigma)
    expected = math.exp(-_R * t) * (_F - K)
    assert (c - p) == pytest.approx(expected, abs=1e-8)
