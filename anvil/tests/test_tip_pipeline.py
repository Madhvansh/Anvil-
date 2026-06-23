"""Shared tip pipeline + intraday pass + the Baltussen expiry-gamma factor."""

from types import SimpleNamespace

from anvil.factors.index_options import expiry_gamma
from anvil.ingest.demo import build_demo_chain
from anvil.ledger.ledger import CalibrationLedger
from anvil.tips.intraday import run_intraday
from anvil.tips.pipeline import tips_for_chain
from anvil.tips.store import IssuedTipStore, TipValidationStore


def _chain():
    return build_demo_chain("NIFTY", spot=24000.0, expiry="2026-06-26", timestamp="2026-06-12T15:30:00+05:30")


# ---- Baltussen expiry-gamma factor ----
def _gctx(days, label, tg):
    return SimpleNamespace(
        event={"days_to_expiry": days},
        regime=SimpleNamespace(label=label),
        gex=SimpleNamespace(total_gex=tg, zero_gamma_flip=24000.0),
    )


def test_expiry_gamma_fires_near_expiry_short_gamma():
    s = expiry_gamma(_gctx(0.5, "negative_gamma_trend_amplify", -2.0e6))
    assert s.fired and s.direction == "long_vol" and s.edge_tier == "strong"
    assert s.drivers["india_unvalidated"] is True
    assert s.drivers["mechanism"] == "baltussen_expiry_momentum"


def test_expiry_gamma_quiet_far_from_expiry_or_positive_gamma():
    assert not expiry_gamma(_gctx(5.0, "negative_gamma_trend_amplify", -2.0e6)).fired
    assert not expiry_gamma(_gctx(0.5, "positive_gamma_mean_revert", 2.0e6)).fired


# ---- shared pipeline ----
def test_tips_for_chain_builds_default_watchlist_without_store():
    ctx, bucket, signals, tips = tips_for_chain(_chain(), source="tip_live", equity=1_000_000.0)
    assert tips, "demo chain should yield tradeable tips"
    assert all(t.tier == "watchlist" for t in tips)  # no gate store → default tier
    assert bucket in ("pin_low_vol", "trend_high_vol", "event_crush", "neutral")
    assert ctx.spot == 24000.0
    assert signals  # factors ran


def test_tips_for_chain_gates_to_watchlist_with_empty_store(tmp_path):
    vs = TipValidationStore(path=str(tmp_path / "tv.duckdb"))
    try:
        _, _, _, tips = tips_for_chain(_chain(), source="tip_live", equity=1_000_000.0, validation_store=vs)
        assert all(t.tier == "watchlist" for t in tips)  # no measured evidence → no headline
    finally:
        vs.close()


# ---- intraday pass ----
class _FixedConnector:
    name = "upstox"
    provides_positions = False

    def get_chain(self, underlying="NIFTY", expiry=None):
        return _chain()


def test_run_intraday_issues_and_persists_on_tip_live(tmp_path):
    led = CalibrationLedger(path=str(tmp_path / "l.duckdb"))
    vs = TipValidationStore(path=str(tmp_path / "tv.duckdb"))
    iss = IssuedTipStore(path=str(tmp_path / "iss.duckdb"))
    try:
        res = run_intraday(["NIFTY"], connector=_FixedConnector(), ledger=led,
                           validation_store=vs, issued_store=iss)
        assert res["source"] == "tip_live"
        assert res["issued"] >= 1
        assert res["headline"] == []  # honest default: no measured evidence yet
        assert len(iss.recent("NIFTY")) == res["issued"]
        # issued tips are pending on the public tip curve (recorded, not yet resolved)
        assert led.metrics_for_tips()["tip_live"]["pending_count"] == res["issued"]
    finally:
        led.close()
        vs.close()
        iss.close()
