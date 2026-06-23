"""End-to-end ingest: fetch a chain, compute Black-76 Greeks, persist, and register the snapshot.

The snapshot_id is deterministic in (underlying, expiry, snapshot_ts, source) so re-ingesting the
same fixture yields the same id and overwrites the same Parquet file — which is what makes the
reproducibility self-check in scripts/demo_phase0.py meaningful.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from ..config import get_settings
from ..data.source import ChainRequest, DataSource
from ..domain.models import GreeksResult, OptionChain
from ..quant.greeks_service import compute_chain_greeks
from ..storage.duck import DuckStore
from ..storage.sqlite_meta import SqliteMeta


@dataclass(frozen=True)
class IngestResult:
    snapshot_id: str
    chain: OptionChain
    greeks: list[GreeksResult]
    chain_path: str
    greeks_path: str
    row_count: int


def snapshot_id_for(chain: OptionChain, source_name: str) -> str:
    expiry = chain.rows[0].expiry if chain.rows else None
    expiry_tag = expiry.strftime("%Y%m%d") if expiry else "noexp"
    ts_tag = chain.snapshot_ts.strftime("%Y%m%dT%H%M%S")
    return f"{chain.underlying}_{expiry_tag}_{ts_tag}_{source_name}"


def _default_store() -> DuckStore:
    return DuckStore(get_settings().snapshots_dir)


def _default_meta() -> SqliteMeta:
    return SqliteMeta(get_settings().sqlite_path)


def ingest(
    source: DataSource,
    request: ChainRequest,
    *,
    store: DuckStore | None = None,
    meta: SqliteMeta | None = None,
) -> IngestResult:
    store = store or _default_store()
    meta = meta or _default_meta()
    meta.seed_instruments()

    started_at = datetime.now(UTC).isoformat()
    try:
        chain = source.fetch_chain(request)
        snapshot_id = snapshot_id_for(chain, source.name)
        greeks = compute_chain_greeks(chain)

        chain_path = store.write_snapshot(snapshot_id, chain)
        greeks_path = store.write_greeks(snapshot_id, chain, greeks)
        expiry = chain.rows[0].expiry.isoformat() if chain.rows else None

        meta.register_snapshot(
            snapshot_id=snapshot_id,
            underlying=chain.underlying,
            expiry=expiry,
            snapshot_ts=chain.snapshot_ts.isoformat(),
            source=source.name,
            chain_path=chain_path,
            greeks_path=greeks_path,
            row_count=len(greeks),
        )
        meta.record_ingest_run(
            run_id=f"{snapshot_id}:run",
            snapshot_id=snapshot_id,
            source=source.name,
            status="ok",
            started_at=started_at,
            finished_at=datetime.now(UTC).isoformat(),
        )
        return IngestResult(
            snapshot_id=snapshot_id,
            chain=chain,
            greeks=greeks,
            chain_path=chain_path,
            greeks_path=greeks_path,
            row_count=len(greeks),
        )
    except Exception as exc:  # record the failure, then re-raise
        meta.record_ingest_run(
            run_id=f"{request.underlying}:{started_at}:run",
            snapshot_id=None,
            source=getattr(source, "name", "unknown"),
            status="error",
            started_at=started_at,
            finished_at=datetime.now(UTC).isoformat(),
            error=str(exc),
        )
        raise
