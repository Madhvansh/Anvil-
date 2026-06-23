"""Phase 0 end-to-end proof.

Ingests a fixture chain → computes Black-76 Greeks → stores (Parquet + SQLite) → re-reads via the
query path → asserts the re-read Greeks equal the freshly computed ones (reproducibility self-check).
Exit code 0 on success, 1 on any mismatch — this is the gate the CI smoke step runs.

    python scripts/demo_phase0.py --underlying NIFTY
"""

from __future__ import annotations

import argparse
import sys

from oip.config import get_settings
from oip.data.fixture_replay import FixtureDataSource
from oip.data.source import ChainRequest
from oip.pipeline.ingest import ingest
from oip.storage.duck import DuckStore
from oip.storage.sqlite_meta import SqliteMeta

_TOL = 1e-9


def _fmt(v, d=2):
    return "—" if v is None else f"{v:,.{d}f}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 0 ingest → Greeks → store → query demo")
    ap.add_argument("--underlying", default="NIFTY")
    args = ap.parse_args()

    settings = get_settings()
    store = DuckStore(settings.snapshots_dir)
    meta = SqliteMeta(settings.sqlite_path)
    source = FixtureDataSource()

    print(f"== Phase 0 demo — {args.underlying} ==")
    print(f"data dir   : {settings.data_dir}")
    print(f"datasource : {source.name} (requires_credentials={source.requires_credentials})\n")

    # 1-4. ingest = fetch → compute Greeks → store → register
    result = ingest(source, ChainRequest(underlying=args.underlying), store=store, meta=meta)
    chain = result.chain

    print("[1] Ingested chain")
    print(f"    spot            : {_fmt(chain.spot)}")
    print(f"    future_price    : {_fmt(chain.future_price)}  ({chain.future_price_source.value})")
    print(f"    snapshot_ts     : {chain.snapshot_ts.isoformat()}")
    print(f"    risk_free_rate  : {chain.risk_free_rate}")
    print(f"    legs priced     : {result.row_count}")
    print(f"[2] snapshot_id     : {result.snapshot_id}")
    print(f"    chain parquet   : {result.chain_path}")
    print(f"    greeks parquet  : {result.greeks_path}\n")

    # 5. re-read via the query path (SQLite resolves latest → DuckDB joins)
    latest = meta.latest_snapshot_id(args.underlying)
    joined = store.read_chain_with_greeks(latest)
    print(f"[3] Re-read latest snapshot ({latest}) — {len(joined)} legs")
    print(f"    {'strike':>8} {'type':>4} {'IV':>7} {'delta':>8} {'gamma':>9} {'theta/d':>9} {'vega/1%':>9}")
    for r in joined:
        print(f"    {r['strike']:>8.0f} {r['option_type']:>4} {_fmt(r['iv_used']*100,2):>7} "
              f"{_fmt(r['delta'],3):>8} {_fmt(r['gamma'],5):>9} {_fmt(r['theta_per_day'],2):>9} "
              f"{_fmt(r['vega_per_pct'],2):>9}")

    # 6. reproducibility self-check: stored == freshly computed
    fresh = {(g.strike, g.option_type.value): g for g in result.greeks}
    mismatches = []
    for r in joined:
        g = fresh.get((r["strike"], r["option_type"]))
        if g is None:
            mismatches.append(f"missing fresh greek for {r['strike']}{r['option_type']}")
            continue
        for field, stored in (("delta", r["delta"]), ("gamma", r["gamma"]),
                              ("theta_per_day", r["theta_per_day"]), ("vega_per_pct", r["vega_per_pct"]),
                              ("rho", r["rho"]), ("price", r["price"])):
            if abs(stored - getattr(g, field if field != "price" else "price")) > _TOL:
                mismatches.append(f"{r['strike']}{r['option_type']}.{field}: {stored} != stored")

    print()
    if mismatches:
        print(f"[FAIL] reproducibility check found {len(mismatches)} mismatch(es):")
        for m in mismatches[:10]:
            print(f"    - {m}")
        return 1
    print(f"[PASS] reproducibility check — all {len(joined)} legs re-read byte-stable (tol={_TOL}).")
    print("\nDisclaimer: computed analytics (Black-76 on the futures price), not investment advice.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
