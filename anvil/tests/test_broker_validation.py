"""Broker-Greeks validation gate.

The rail says: validate computed Greeks against broker-shown values for known strikes. Brokers
(e.g. Upstox) serve their own Greeks alongside the chain; capture a handful into
``tests/fixtures/broker_greeks.json`` and this test compares our Black-76 engine to them within
tolerance. It SKIPS cleanly while the fixture is empty, so it activates the moment real values
are captured — turning a doc promise into a build gate.

Fixture rows: {"option_type":"CE"|"PE","F":...,"strike":...,"T":...,"iv":...,"r":0.065,
               "delta":...,"gamma":...,"theta_per_day":...,"vega_per_pct":...,"tol":{...}}
"""

import json
from pathlib import Path

import pytest

from anvil.engine import greeks as gk
from anvil.models import OptionType

FIX = Path(__file__).parent / "fixtures" / "broker_greeks.json"


def _cases():
    if not FIX.exists():
        return []
    try:
        return json.loads(FIX.read_text())
    except json.JSONDecodeError:
        return []


def test_engine_matches_broker_greeks():
    cases = _cases()
    if not cases:
        pytest.skip(
            "No captured broker Greeks yet — drop real broker-shown values into "
            "tests/fixtures/broker_greeks.json to activate this validation gate."
        )
    for c in cases:
        g = gk.compute_greeks(
            OptionType(c["option_type"]), c["F"], c["strike"], c["T"], c.get("r", 0.065), c["iv"]
        )
        tol = c.get("tol", {})
        assert g.delta == pytest.approx(c["delta"], abs=tol.get("delta", 0.02)), c
        if "gamma" in c:
            assert g.gamma == pytest.approx(c["gamma"], abs=tol.get("gamma", 0.001)), c
        if "theta_per_day" in c:
            assert g.theta == pytest.approx(c["theta_per_day"], abs=tol.get("theta", 2.0)), c
        if "vega_per_pct" in c:
            assert g.vega == pytest.approx(c["vega_per_pct"], abs=tol.get("vega", 2.0)), c
