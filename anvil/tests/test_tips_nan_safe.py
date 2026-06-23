"""M1 regression: the live tips surface must NEVER 500 on an overlay.

Two bugs took the live product down (see anvil/go_live.log, anvil/docs/TIPS_REBUILD.md):
  1. validation cells store NaN (under-sampled t_stat/dsr/pbo) → Starlette's allow_nan=False JSON
     encoder 500s /api/tips/track-record. Fixed by routing every tips/momentum payload through
     engine.util.json_safe.
  2. a calibration service that raises must degrade to identity, never sink the always-present
     prediction (predict.py).
"""

from __future__ import annotations

import math

import pytest
from fastapi.testclient import TestClient

import anvil.api.routers.tips as tipsmod
from anvil.api.app import app
from anvil.db import engine as dbengine
from anvil.ingest.base import attach_parity_forward
from anvil.ingest.demo import DemoConnector
from anvil.ledger.ledger import CalibrationLedger
from anvil.tips.predict import predict_for_chain
from anvil.tips.store import IssuedTipStore, TipValidationReport, TipValidationStore

OWNER = {"email": "owner@anvil.test", "password": "supersecret1"}


@pytest.fixture
def client(tmp_path):
    dbengine.init_engine(f"sqlite+aiosqlite:///{(tmp_path / 'nan.db').as_posix()}")
    with TestClient(app) as c:
        yield c


def _isolate_stores(monkeypatch, tmp_path):
    monkeypatch.setattr(tipsmod, "TipValidationStore", lambda path=None: TipValidationStore(str(tmp_path / "tv.duckdb")))
    monkeypatch.setattr(tipsmod, "IssuedTipStore", lambda path=None: IssuedTipStore(str(tmp_path / "iss.duckdb")))
    monkeypatch.setattr(tipsmod, "CalibrationLedger", lambda path=None: CalibrationLedger(str(tmp_path / "l.duckdb")))


def _seed_nan_cell(tmp_path):
    """Write an under-sampled validation cell with NaN stats — exactly what validate_cells persists."""
    store = TipValidationStore(str(tmp_path / "tv.duckdb"))
    try:
        store.upsert(TipValidationReport(
            structure="long_call", regime_bucket="trend_up", underlying="NIFTY",
            n=3, win_rate=float("nan"), mean_conviction=float("nan"), mean_net_pnl=float("nan"),
            cost_adjusted_edge=float("nan"), t_stat=float("nan"), dsr=float("nan"),
            pbo=float("nan"), robustness_p_low=float("nan"), headline_eligible=False,
            updated_ts="2026-06-23T00:00:00Z", model_version="phase0-1.1.0"))
    finally:
        store.close()


def test_track_record_serializes_nan_cells(client, monkeypatch, tmp_path):
    client.post("/auth/register", json=OWNER)
    _isolate_stores(monkeypatch, tmp_path)
    _seed_nan_cell(tmp_path)

    r = client.get("/api/tips/track-record")
    assert r.status_code == 200, r.text  # was 500: "Out of range float values are not JSON compliant: nan"
    cell = next(c for c in r.json()["cells"] if c["underlying"] == "NIFTY")
    assert cell["t_stat"] is None and cell["dsr"] is None  # NaN -> None


def test_tips_endpoint_serializes_with_nan_cell(client, monkeypatch, tmp_path):
    client.post("/auth/register", json=OWNER)
    _isolate_stores(monkeypatch, tmp_path)
    _seed_nan_cell(tmp_path)

    r = client.get("/api/tips/NIFTY")
    assert r.status_code == 200, r.text
    assert r.json()["prediction"]["underlying"] == "NIFTY"


def test_calibration_that_raises_degrades_to_identity():
    """A calibration service whose calibrate() throws must not sink the never-empty prediction."""

    class _Boom:
        def is_calibrated(self, *_a, **_k):
            return True

        def calibrate(self, *_a, **_k):
            raise RuntimeError("malformed calibrator row")

    chain = attach_parity_forward(DemoConnector().get_chain("NIFTY"))
    ctx, bucket, signals, pred, tips = predict_for_chain(
        chain, source="demo", equity=1_000_000.0, calibration=_Boom())
    assert pred.direction
    assert 0.0 <= pred.confidence <= 1.0 and math.isfinite(pred.confidence)
    assert pred.calibrated_confidence is None  # degraded to identity, raw confidence stands
