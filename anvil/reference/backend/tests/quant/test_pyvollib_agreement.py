"""Third-party cross-check: engine price/delta/gamma agree with vollib's independent code.

The Black-1976 model in vollib/py_vollib is the `black` module. Skipped if unavailable (the engine
has a SciPy fallback). delta/gamma are compared because vollib returns them in raw units (no
scaling), matching the engine's contract; theta/vega/rho are validated by the finite-difference
suite instead, avoiding scaling assumptions here.
"""

from __future__ import annotations

import pytest

from oip.quant import black76

pytestmark = [pytest.mark.validation]

pv_black = pytest.importorskip(
    "vollib.black", reason="vollib not installed; SciPy fallback covers correctness"
)
pv_greeks = pytest.importorskip("vollib.black.greeks.analytical")

_CASES = [
    ("c", 22000.0, 22000.0, 30 / 365, 0.065, 0.14),
    ("p", 22000.0, 22500.0, 7 / 365, 0.065, 0.18),
    ("c", 48000.0, 48000.0, 14 / 365, 0.065, 0.20),
]


@pytest.mark.parametrize("flag,F,K,t,r,sigma", _CASES)
def test_engine_agrees_with_vollib(flag, F, K, t, r, sigma):
    assert black76.price(flag, F, K, t, r, sigma) == pytest.approx(
        pv_black.black(flag, F, K, t, r, sigma), rel=1e-6, abs=1e-6
    )
    assert black76.delta(flag, F, K, t, r, sigma) == pytest.approx(
        pv_greeks.delta(flag, F, K, t, r, sigma), rel=1e-6, abs=1e-6
    )
    assert black76.gamma(F, K, t, r, sigma) == pytest.approx(
        pv_greeks.gamma(flag, F, K, t, r, sigma), rel=1e-6, abs=1e-6
    )
