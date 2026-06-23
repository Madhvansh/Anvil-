"""Known-value tests: engine price/Greeks vs the independent SciPy reference + an absolute anchor.

The engine's price path (py_vollib when available) is cross-checked against the hand-written SciPy
oracle, and the ATM case is anchored to an externally-derivable number so both can't drift together.
"""

from __future__ import annotations

import math

import pytest

from oip.quant import black76

pytestmark = [pytest.mark.validation]


def test_known_values_match_reference(known_values, ref):
    rtol = known_values["tolerance"]["rtol"]
    atol = known_values["tolerance"]["atol"]
    for case in known_values["cases"]:
        flag, F, K, t, r, s = (
            case["flag"], case["F"], case["K"], case["t"], case["r"], case["sigma"]
        )
        ctx = case["name"]

        assert black76.price(flag, F, K, t, r, s) == pytest.approx(
            ref.price(flag, F, K, t, r, s), rel=rtol, abs=atol
        ), ctx
        assert black76.delta(flag, F, K, t, r, s) == pytest.approx(
            ref.delta(flag, F, K, t, r, s), rel=rtol, abs=atol
        ), ctx
        assert black76.gamma(F, K, t, r, s) == pytest.approx(
            ref.gamma(flag, F, K, t, r, s), rel=rtol, abs=atol
        ), ctx
        assert black76.vega(F, K, t, r, s) == pytest.approx(
            ref.vega(flag, F, K, t, r, s), rel=rtol, abs=atol
        ), ctx
        assert black76.theta(flag, F, K, t, r, s) == pytest.approx(
            ref.theta(flag, F, K, t, r, s), rel=rtol, abs=atol
        ), ctx
        assert black76.rho(flag, F, K, t, r, s) == pytest.approx(
            ref.rho(flag, F, K, t, r, s), rel=rtol, abs=atol
        ), ctx


def test_absolute_price_anchor(known_values):
    """At least one case anchors the absolute price scale to an externally-derivable number."""
    anchored = [c for c in known_values["cases"] if "approx_price" in c]
    assert anchored, "expected at least one anchored case"
    for case in anchored:
        p = black76.price(case["flag"], case["F"], case["K"], case["t"], case["r"], case["sigma"])
        assert p == pytest.approx(case["approx_price"], abs=case["approx_price_atol"]), case["name"]


def test_atm_call_equals_put(known_values):
    """At F == K, put-call parity forces call price == put price (discount factor cancels K-F=0)."""
    for case in known_values["cases"]:
        if not case.get("atm"):
            continue
        F, K, t, r, s = case["F"], case["K"], case["t"], case["r"], case["sigma"]
        c = black76.price("c", F, K, t, r, s)
        p = black76.price("p", F, K, t, r, s)
        assert math.isclose(c, p, abs_tol=1e-9), case["name"]
