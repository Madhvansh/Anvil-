"""Phase 4 PERSONAL_MODE hard wall (ADR 0006): public serialization strips the actionable/sized/risk
fields; the gate0 interlock arms emission; the owner route is owner+armed gated. Default config is OFF
=> the app is a public analytics surface."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import anvil.api.routers.tips as tipsmod
from anvil import gating
from anvil.api.app import app
from anvil.auth import deps as authdeps
from anvil.db import engine as dbengine
from anvil.ledger.ledger import CalibrationLedger
from anvil.tips.store import IssuedTipStore, TipValidationStore
from anvil.tips.types import Prediction

OWNER = {"email": "owner@anvil.test", "password": "supersecret1"}


def _pred(**kw) -> Prediction:
    base = dict(
        underlying="NIFTY", as_of="t", spot=100.0, direction="neutral", confidence=0.6,
        confidence_basis="candidate_conviction", prob_above=0.5, prob_below=0.5,
        expected_move=10.0, target_band=[90.0, 110.0], regime="x", regime_bucket="b",
    )
    base.update(kw)
    return Prediction(**base)


# --- serialization is the boundary -----------------------------------------
def test_prediction_owner_vs_public_serialization():
    p = _pred(has_actionable_tip=True, actionable_tip={"legs": [1]},
              risk_distribution={"cvar_95": 1.0}, risk_of_ruin=0.1, forward_drawdown={"p50": 0.2})
    pub = p.to_dict(owner=False)
    assert pub["actionable_tip"] is None and pub["has_actionable_tip"] is False
    assert pub["risk_distribution"] is None and pub["risk_of_ruin"] is None and pub["forward_drawdown"] is None
    assert pub == p.public_dict()
    # analytics fields survive on the public surface
    assert pub["confidence"] == 0.6 and pub["direction"] == "neutral" and pub["target_band"] == [90.0, 110.0]
    own = p.to_dict(owner=True)
    assert own["actionable_tip"] == {"legs": [1]} and own["has_actionable_tip"] is True
    assert own["risk_distribution"] == {"cvar_95": 1.0} and own["risk_of_ruin"] == 0.1


# --- the Gate-0 interlock ---------------------------------------------------
class _FakeStore:
    def __init__(self, cells):
        self._c = cells

    def all(self):
        return self._c

    def close(self):
        pass


def test_gate0_passed_and_armed(monkeypatch):
    none_eligible = _FakeStore([{"headline_eligible": False, "t_stat": 5.0}])
    eligible = _FakeStore([{"headline_eligible": True, "t_stat": 3.5}])
    weak = _FakeStore([{"headline_eligible": True, "t_stat": 2.0}])  # t < 3 -> not passed
    assert gating.gate0_passed(none_eligible) is False
    assert gating.gate0_passed(eligible) is True
    assert gating.gate0_passed(weak) is False
    # armed = personal_mode AND gate0_passed
    monkeypatch.setattr(gating, "SETTINGS", type("S", (), {"personal_mode": False})())
    assert gating.personal_mode_armed(eligible) is False
    monkeypatch.setattr(gating, "SETTINGS", type("S", (), {"personal_mode": True})())
    assert gating.personal_mode_armed(eligible) is True
    assert gating.personal_mode_armed(none_eligible) is False


# --- the owner-only dependency ---------------------------------------------
class _User:
    def __init__(self, role="owner"):
        self.role = role


def test_require_personal_owner_logic(monkeypatch):
    user = _User(role="owner")
    monkeypatch.setattr(authdeps, "SETTINGS", type("S", (), {"personal_mode": False})())
    with pytest.raises(HTTPException) as e:
        asyncio.run(authdeps.require_personal_owner(user))
    assert e.value.status_code == 403  # personal mode off

    monkeypatch.setattr(authdeps, "SETTINGS", type("S", (), {"personal_mode": True})())
    assert asyncio.run(authdeps.require_personal_owner(user)) is user  # owner ok

    with pytest.raises(HTTPException) as e2:
        asyncio.run(authdeps.require_personal_owner(_User(role="viewer")))
    assert e2.value.status_code == 403  # non-owner blocked


# --- the public API surface (default config = personal mode OFF) ------------
@pytest.fixture
def client(tmp_path):
    dbengine.init_engine(f"sqlite+aiosqlite:///{(tmp_path / 'wall.db').as_posix()}")
    with TestClient(app) as c:
        yield c


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(tipsmod, "TipValidationStore", lambda path=None: TipValidationStore(str(tmp_path / "tv.duckdb")))
    monkeypatch.setattr(tipsmod, "IssuedTipStore", lambda path=None: IssuedTipStore(str(tmp_path / "iss.duckdb")))
    monkeypatch.setattr(tipsmod, "CalibrationLedger", lambda path=None: CalibrationLedger(str(tmp_path / "l.duckdb")))


def test_public_tips_have_no_actionable(client, monkeypatch, tmp_path):
    assert client.post("/auth/register", json=OWNER).status_code == 200
    _isolate(monkeypatch, tmp_path)
    body = client.get("/api/tips/NIFTY").json()
    assert body["prediction"]["actionable_tip"] is None
    assert body["prediction"]["has_actionable_tip"] is False
    assert body["headline"] == [] and body["watchlist"] == []
    assert body.get("personal_mode") is False
    # analytics still served
    assert body["prediction"]["direction"] and 0.0 <= body["prediction"]["confidence"] <= 1.0


def test_actionable_route_403_when_personal_mode_off(client):
    assert client.post("/auth/register", json=OWNER).status_code == 200
    # personal_mode defaults OFF -> require_personal_owner 403 (no actionable surface by default)
    assert client.get("/api/tips/NIFTY/actionable").status_code == 403
