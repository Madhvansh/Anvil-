"""Pipeline ingest: persists a snapshot, registers it, and reads back reproducibly."""

from __future__ import annotations

from datetime import date

import pytest

from oip.data.source import ChainRequest
from oip.pipeline.ingest import ingest, snapshot_id_for
from oip.quant.greeks_service import compute_chain_greeks
from oip.storage.duck import DuckStore
from oip.storage.sqlite_meta import SqliteMeta

pytestmark = [pytest.mark.unit]


class FakeSource:
    """A DataSource that returns a fixed in-memory chain."""

    def __init__(self, chain):
        self._chain = chain

    @property
    def name(self) -> str:
        return "fake"

    @property
    def requires_credentials(self) -> bool:
        return False

    def fetch_chain(self, request: ChainRequest):
        return self._chain

    def list_expiries(self, underlying: str) -> list[date]:
        return [self._chain.rows[0].expiry]


def test_ingest_persists_registers_and_reads_back(tmp_path, sample_chain):
    store = DuckStore(tmp_path / "snap")
    meta = SqliteMeta(tmp_path / "m.sqlite")

    result = ingest(FakeSource(sample_chain), ChainRequest(underlying="NIFTY"), store=store, meta=meta)

    assert result.row_count == 6
    assert result.snapshot_id == snapshot_id_for(sample_chain, "fake")
    assert meta.latest_snapshot_id("NIFTY") == result.snapshot_id

    snap = meta.get_snapshot(result.snapshot_id)
    assert snap["source"] == "fake"
    assert snap["row_count"] == 6
    assert snap["greeks_path"]

    joined = store.read_chain_with_greeks(result.snapshot_id)
    fresh = {(g.strike, g.option_type.value): g for g in compute_chain_greeks(sample_chain)}
    assert len(joined) == 6
    for row in joined:
        g = fresh[(row["strike"], row["option_type"])]
        assert row["delta"] == pytest.approx(g.delta, rel=1e-12, abs=1e-12)
        assert row["price"] == pytest.approx(g.price, rel=1e-12, abs=1e-12)


def test_ingest_snapshot_id_is_idempotent(tmp_path, sample_chain):
    store = DuckStore(tmp_path / "snap")
    meta = SqliteMeta(tmp_path / "m.sqlite")
    r1 = ingest(FakeSource(sample_chain), ChainRequest(underlying="NIFTY"), store=store, meta=meta)
    r2 = ingest(FakeSource(sample_chain), ChainRequest(underlying="NIFTY"), store=store, meta=meta)
    assert r1.snapshot_id == r2.snapshot_id
    assert len(store.read_chain_with_greeks(r2.snapshot_id)) == 6
