"""Tests for meta-label feature extraction + training-set glue + the resolved_payloads reader."""

from __future__ import annotations

from anvil.tips import meta_features as mf
from anvil.tips.types import Tip


def test_features_from_signals_and_regime():
    feats = mf.features_from(0.7, ["mtf_trend", "gamma_flip_sr"], "neutral")
    assert feats["conviction"] == 0.7 and feats["n_signals"] == 2.0
    assert feats["f_momentum"] == 1.0 and feats["f_dealer"] == 1.0
    assert feats["f_flow"] == 0.0 and feats["f_chain"] == 0.0
    assert feats["r_neutral"] == 1.0 and feats["r_trend_high_vol"] == 0.0
    assert set(feats) == set(mf.FEATURE_NAMES)


class _FakeStore:
    def __init__(self, rows):
        self._rows = rows

    def resolved_payloads(self, sources=("tip_live",)):
        return self._rows


def test_training_rows_and_train_from_store():
    rows = []
    # synthetic: a call is "correct" when momentum AND high conviction → meta-label should learn it
    for i in range(160):
        mom = i % 2
        conv = 0.75 if mom else 0.4
        payload = {"conviction": conv, "signals_fired": (["mtf_trend"] if mom else ["smart_money_block"]),
                   "regime_bucket": "neutral"}
        rows.append((payload, mom))
    store = _FakeStore(rows)
    trows = mf.training_rows(store)
    assert len(trows) == 160 and "correct" in trows[0]
    ml = mf.train_from_store(store)
    assert ml is not None
    p_hi = ml.predict(mf.features_from(0.75, ["mtf_trend"], "neutral"))
    p_lo = ml.predict(mf.features_from(0.4, ["smart_money_block"], "neutral"))
    assert p_hi > p_lo


def test_train_from_store_abstains_cold_start():
    assert mf.train_from_store(_FakeStore([]), min_samples=60) is None


def _minimal_tip(**kw):
    base = dict(
        underlying="NIFTY", created_ts="2026-06-23T10:00:00+05:30", resolve_ts="2026-06-24",
        horizon_days=1.0, structure="iron_condor", direction="neutral", legs=[],
        conviction=0.66, edge_prob=0.6, gross_ev=10.0, round_trip_cost=2.0, cost_adjusted_ev=8.0,
        max_loss=100.0, max_profit=50.0, entry_debit_credit=5.0,
        signals_fired=["mtf_trend"], regime_bucket="neutral", source="tip_live")
    base.update(kw)
    return Tip(**base)


def test_resolved_payloads_roundtrip(tmp_path):
    from anvil.tips.store import IssuedTipStore

    st = IssuedTipStore(str(tmp_path / "iss.duckdb"))
    try:
        tip = _minimal_tip()
        st.record(tip)
        st.mark_resolved(tip.tip_id, outcome=1, resolved_ts="2026-06-24T16:00:00+05:30", net_pnl=40.0, ret=0.4)
        payloads = st.resolved_payloads(("tip_live",))
        assert len(payloads) == 1
        pd, outcome = payloads[0]
        assert outcome == 1 and pd["conviction"] == 0.66 and "mtf_trend" in pd["signals_fired"]
        # and it feeds the meta-feature extractor
        feats = mf.features_from_payload(pd)
        assert feats["f_momentum"] == 1.0 and feats["conviction"] == 0.66
    finally:
        st.close()
