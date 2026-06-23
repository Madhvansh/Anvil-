"""Capture a fresh NSE option-chain fixture (requires network; NOT used by tests/CI).

    python scripts/record_fixture.py --underlying NIFTY

Writes data/fixtures/nse_chain_{UNDERLYING}_{YYYY-MM-DD}.json in the wrapper format the
FixtureDataSource expects. The NSE chain endpoint does not carry a futures price, so future_price
is left null and normalize derives a tagged cost-of-carry forward. See docs/PHASE1_BACKLOG.md A2.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime

from oip.config import get_settings
from oip.data.normalize import parse_nse_timestamp
from oip.data.nse_public import NsePublicDataSource


def main() -> int:
    ap = argparse.ArgumentParser(description="Record a live NSE option-chain fixture")
    ap.add_argument("--underlying", default="NIFTY")
    args = ap.parse_args()
    underlying = args.underlying.upper()

    settings = get_settings()
    source = NsePublicDataSource()

    print(f"Fetching {underlying} option chain from NSE (public endpoint)…")
    try:
        raw = source._fetch_raw(underlying)
    except Exception as exc:  # network/blocking is expected to be flaky
        print(f"[ERROR] NSE fetch failed: {exc}", file=sys.stderr)
        print("This script needs live network access to NSE; it is not part of the build.", file=sys.stderr)
        return 1

    try:
        snap_date = parse_nse_timestamp(raw["records"]["timestamp"]).date().isoformat()
    except Exception:
        snap_date = datetime.now(UTC).date().isoformat()

    wrapper = {
        "_oip_meta": {
            "captured_at": datetime.now(UTC).isoformat(),
            "underlying": underlying,
            "exchange": "NSE",
            "future_price": None,
            "future_price_source": "derived_cost_of_carry",
            "risk_free_rate": settings.default_risk_free_rate,
            "note": "Captured from NSE public option-chain endpoint. No real future recorded; "
                    "normalize derives a tagged cost-of-carry forward.",
        },
        "raw": raw,
    }

    settings.fixtures_dir.mkdir(parents=True, exist_ok=True)
    out = settings.fixtures_dir / f"nse_chain_{underlying}_{snap_date}.json"
    out.write_text(json.dumps(wrapper, indent=2))
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
