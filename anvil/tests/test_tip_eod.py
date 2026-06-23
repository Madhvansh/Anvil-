"""EOD/swing tip cycle: issue → gate (watchlist without evidence) → persist → resolve held-to-expiry,
with synthetic (demo) tips kept off the public tip curve and real (tip_live) tips on it."""

from anvil.ingest.demo import build_demo_chain
from anvil.ledger.ledger import CalibrationLedger
from anvil.tips.eod import run_tip_cycle, tip_source_for
from anvil.tips.store import IssuedTipStore, TipValidationStore


class _FixedConnector:
    """Deterministic connector: always the same demo chain (fixed spot/expiry/timestamp)."""

    def __init__(self, name: str = "upstox"):
        self.name = name
        self.provides_positions = False

    def get_chain(self, underlying: str = "NIFTY", expiry=None):
        return build_demo_chain(underlying.upper(), spot=24000.0, expiry="2026-06-26",
                                timestamp="2026-06-12T15:30:00+05:30")


def _stores(tmp_path):
    return (
        CalibrationLedger(path=str(tmp_path / "l.duckdb")),
        TipValidationStore(path=str(tmp_path / "tv.duckdb")),
        IssuedTipStore(path=str(tmp_path / "iss.duckdb")),
    )


def test_source_mapping():
    assert tip_source_for("demo") == "demo"
    assert tip_source_for("seed") == "demo"
    assert tip_source_for("upstox") == "tip_live"
    assert tip_source_for("groww") == "tip_live"


def test_issue_persist_and_gate_watchlist(tmp_path):
    led, vs, iss = _stores(tmp_path)
    try:
        res = run_tip_cycle(["NIFTY"], connector=_FixedConnector("upstox"),
                            ledger=led, validation_store=vs, issued_store=iss)
        assert res["source"] == "tip_live"
        assert res["issued"] >= 1
        # no validation evidence yet → everything is watchlist, headline is empty (honest default)
        assert res["headline"] == []
        assert len(res["watchlist"]) == res["issued"]
        # persisted with full payloads for the API feed
        assert len(iss.recent("NIFTY")) == res["issued"]
    finally:
        led.close()
        vs.close()
        iss.close()


def test_resolution_of_due_tips_lands_on_tip_live_curve(tmp_path):
    led, vs, iss = _stores(tmp_path)
    try:
        res = run_tip_cycle(["NIFTY"], connector=_FixedConnector("upstox"),
                            ledger=led, validation_store=vs, issued_store=iss,
                            realized={"NIFTY": 24000.0}, as_of="2026-06-26")
        assert res["issued"] >= 1
        assert res["resolved"]["NIFTY"] == res["issued"]  # all due tips settled
        curve = led.metrics_for_tips()["tip_live"]
        assert curve["resolved_count"] == res["issued"]
        assert led.metrics()["resolved_count"] == 0  # nothing leaks to the public probability curve
    finally:
        led.close()
        vs.close()
        iss.close()


def test_demo_tips_excluded_from_public_tip_curve(tmp_path):
    led, vs, iss = _stores(tmp_path)
    try:
        res = run_tip_cycle(["NIFTY"], connector=_FixedConnector("demo"),
                            ledger=led, validation_store=vs, issued_store=iss,
                            realized={"NIFTY": 24000.0}, as_of="2026-06-26")
        assert res["source"] == "demo"
        assert res["resolved"]["NIFTY"] == res["issued"]
        # synthetic tips resolve, but never touch the public tip_live/tip_backtest curve
        tips = led.metrics_for_tips()
        assert tips["tip_live"]["resolved_count"] == 0
        assert tips["tip_backtest"]["resolved_count"] == 0
        assert len(iss.recent("NIFTY")) == res["issued"]  # but they ARE persisted/auditable
    finally:
        led.close()
        vs.close()
        iss.close()


def test_rerun_is_idempotent_no_duplicate_tips(tmp_path):
    led, vs, iss = _stores(tmp_path)
    try:
        r1 = run_tip_cycle(["NIFTY"], connector=_FixedConnector("upstox"),
                           ledger=led, validation_store=vs, issued_store=iss)
        n_after_first = len(iss.recent("NIFTY", limit=1000))
        r2 = run_tip_cycle(["NIFTY"], connector=_FixedConnector("upstox"),
                           ledger=led, validation_store=vs, issued_store=iss)
        n_after_second = len(iss.recent("NIFTY", limit=1000))
        assert r1["issued"] == r2["issued"]
        assert n_after_first == n_after_second  # content-hashed ids → no duplicate rows
    finally:
        led.close()
        vs.close()
        iss.close()
