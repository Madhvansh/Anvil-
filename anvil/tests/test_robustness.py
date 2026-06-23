"""Audit regressions: payloads are always JSON-safe (no NaN → no HTTP 500)."""

from __future__ import annotations

import math

from anvil.engine.util import json_safe
from anvil.ingest.demo import DemoConnector
from anvil.pipeline import analyze_chain


def _has_nan(o) -> bool:
    if isinstance(o, float):
        return not math.isfinite(o)
    if isinstance(o, dict):
        return any(_has_nan(v) for v in o.values())
    if isinstance(o, (list, tuple)):
        return any(_has_nan(v) for v in o)
    return False


def test_json_safe_strips_non_finite():
    out = json_safe({"a": float("nan"), "b": [1.0, float("inf")], "c": {"d": float("-inf")}, "e": "x", "f": 2})
    assert out == {"a": None, "b": [1.0, None], "c": {"d": None}, "e": "x", "f": 2}


def test_analyze_payload_is_json_safe():
    ch = DemoConnector().get_chain("NIFTY")
    assert not _has_nan(analyze_chain(ch, source="demo"))


def test_analyze_serializes_with_missing_atm_iv():
    # Regression for the em_atm_iv NaN → HTTP 500 bug: wipe ATM iv/ltp so _atm_iv is None while
    # the OTM smile still builds the distribution; em_atm_iv must be None (not NaN), payload safe.
    ch = DemoConnector().get_chain("NIFTY")
    atm = ch.atm_strike()
    for row in ch.rows:
        if row.strike == atm:
            row.iv = None
            row.ltp = None
    payload = analyze_chain(ch, source="demo")
    d = payload.get("implied_distribution")
    if d is not None:
        assert d["em_atm_iv"] is None
    assert not _has_nan(payload)
