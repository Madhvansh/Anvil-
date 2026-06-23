"""Capture broker-shown Greeks into the validation fixture.

The broker-Greeks gate (``tests/test_broker_validation.py``) skips while the fixture is empty
and activates the moment real broker values land in it. Brokers like Upstox serve their own
Greeks + IV alongside the chain; this pulls a handful of near-ATM strikes from the LIVE chain,
resolves the forward, and writes rows in the fixture schema. One command turns the doc promise
into a build gate — run it once real keys are set:

    ANVIL_PRIMARY_SOURCE=upstox ./.venv/Scripts/python.exe -m anvil.ingest.capture NIFTY
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from ..engine.forward import resolve_forward
from ..engine.util import year_fraction
from ..models import OptionChain
from . import get_connector

_FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "broker_greeks.json"


def capture_rows(chain: OptionChain, n: int = 6) -> list[dict]:
    """Build fixture rows from near-ATM strikes that carry broker Greeks + IV."""
    F, _ = resolve_forward(chain)
    T = year_fraction(chain.expiry, chain.timestamp)
    cands = [r for r in chain.rows if r.greeks is not None and r.iv]
    cands.sort(key=lambda r: abs(r.strike - chain.spot))
    rows: list[dict] = []
    for r in cands[:n]:
        rows.append(
            {
                "option_type": r.option_type.value,
                "F": round(float(F), 4),
                "strike": float(r.strike),
                "T": round(float(T), 6),
                "iv": round(float(r.iv), 6),
                "r": 0.065,
                "delta": round(float(r.greeks.delta), 4),
                "gamma": round(float(r.greeks.gamma), 6),
                "theta_per_day": round(float(r.greeks.theta), 3),
                "vega_per_pct": round(float(r.greeks.vega), 3),
                "tol": {"delta": 0.03, "gamma": 0.002, "theta": 3.0, "vega": 3.0},
            }
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    underlying = (argv[0] if argv else "NIFTY").upper()
    conn = get_connector()
    if conn.name == "demo":
        print(
            "Refusing to capture from the demo source — its Greeks are self-generated and would "
            "make the gate a tautology. Set ANVIL_PRIMARY_SOURCE=upstox with real keys first.",
            file=sys.stderr,
        )
        return 2
    chain = conn.get_chain(underlying)
    rows = capture_rows(chain)
    if not rows:
        print(f"No strikes with broker Greeks + IV found for {underlying}.", file=sys.stderr)
        return 1
    _FIXTURE.write_text(json.dumps(rows, indent=2))
    print(f"Wrote {len(rows)} broker-Greeks rows for {underlying} -> {_FIXTURE}")
    print("Run: ./.venv/Scripts/python.exe -m pytest tests/test_broker_validation.py -q")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
