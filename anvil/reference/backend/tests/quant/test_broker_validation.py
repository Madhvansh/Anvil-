"""Validate computed Greeks against broker-shown values (per-strike tolerances).

Non-gating until real broker numbers are captured into broker_greeks_nifty.json (see
docs/PHASE1_BACKLOG.md A1); skips cleanly while 'rows' is empty. Once populated, the
broker_validation marker becomes a required CI gate.
"""

from __future__ import annotations

import pytest

from oip.quant import black76

pytestmark = [pytest.mark.broker_validation]


def test_greeks_within_broker_tolerance(broker_fixture):
    rows = broker_fixture.get("rows") or []
    if not rows:
        pytest.skip("broker_greeks_nifty.json not yet populated with captured numbers")

    F = broker_fixture["future_price"]
    r = broker_fixture["risk_free_rate"]
    for row in rows:
        flag = row["option_type"]
        K, t, iv = row["strike"], row["t_years"], row["broker_iv"]
        broker, tol = row["broker"], row["tol"]

        # Convert engine RAW units to broker presentation units.
        delta = black76.delta(flag, F, K, t, r, iv)
        gamma = black76.gamma(F, K, t, r, iv)
        theta_per_day = black76.theta(flag, F, K, t, r, iv) / 365.0
        vega_per_pct = black76.vega(F, K, t, r, iv) / 100.0

        ctx = f"{K}{flag}"
        assert delta == pytest.approx(broker["delta"], abs=tol["delta"]), ctx
        assert gamma == pytest.approx(broker["gamma"], abs=tol["gamma"]), ctx
        assert theta_per_day == pytest.approx(broker["theta"], abs=tol["theta"]), ctx
        assert vega_per_pct == pytest.approx(broker["vega"], abs=tol["vega"]), ctx
