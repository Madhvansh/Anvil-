"""Terminal payoff, Monte-Carlo robustness, and the headline/watchlist gate."""

from anvil.backtest.robustness import block_bootstrap_edge
from anvil.tips.gate import decide_tier
from anvil.tips.resolve import terminal_payoff
from anvil.tips.store import TipValidationReport, TipValidationStore
from anvil.tips.types import HEADLINE, WATCHLIST, Tip


# ---- terminal payoff (held-to-expiry, exact) ----
def test_long_call_payoff():
    legs = [{"side": "BUY", "lots": 1, "ref_price": 100.0, "instrument_type": "CE", "strike": 24000.0}]
    assert terminal_payoff(legs, lot_size=75, settle=24300.0) == (300.0 - 100.0) * 75  # +15000
    assert terminal_payoff(legs, lot_size=75, settle=23900.0) == (0.0 - 100.0) * 75    # -7500


def test_short_strangle_payoff():
    legs = [
        {"side": "SELL", "lots": 1, "ref_price": 100.0, "instrument_type": "CE", "strike": 24200.0},
        {"side": "SELL", "lots": 1, "ref_price": 90.0, "instrument_type": "PE", "strike": 23800.0},
    ]
    # settle inside both shorts → keep full premium: (100+90)*75
    assert terminal_payoff(legs, 75, 24000.0) == (100.0 + 90.0) * 75
    # settle far above the call → big loss on the call leg
    assert terminal_payoff(legs, 75, 24500.0) == (-(300.0 - 100.0) + 90.0) * 75


def test_future_leg_payoff_is_linear():
    legs = [{"side": "BUY", "lots": 2, "ref_price": 24000.0, "instrument_type": "FUT"}]
    assert terminal_payoff(legs, 75, 24100.0) == (24100.0 - 24000.0) * 2 * 75


# ---- robustness ----
def test_bootstrap_positive_series_has_positive_tail():
    out = block_bootstrap_edge([0.1] * 60, seed=1)
    assert abs(out["mean"] - 0.1) < 1e-9
    assert out["p_low"] > 0


def test_bootstrap_single_trade_is_nan():
    out = block_bootstrap_edge([0.2])
    assert out["p_low"] != out["p_low"]  # NaN


# ---- gate ----
def _tip(structure="iron_condor", bucket="pin_low_vol", cae=500.0):
    return Tip(
        underlying="NIFTY", created_ts="2026-06-19T06:00:00+00:00", resolve_ts="2026-06-24",
        horizon_days=3.0, structure=structure, direction="neutral",
        legs=[{"side": "SELL", "lots": 1, "strike": 24000, "instrument_type": "CE"}], lot_size=75,
        conviction=0.65, edge_prob=0.62, gross_ev=700.0, round_trip_cost=200.0,
        cost_adjusted_ev=cae, max_loss=5000.0, max_profit=2500.0, entry_debit_credit=-2500.0,
        regime_bucket=bucket,
    )


def _report(store, structure, bucket, eligible):
    store.upsert(TipValidationReport(
        structure=structure, regime_bucket=bucket, underlying="NIFTY", n=120, win_rate=0.66,
        mean_conviction=0.63, mean_net_pnl=350.0, cost_adjusted_edge=0.08, t_stat=3.4, dsr=0.97,
        pbo=0.2, robustness_p_low=0.01, headline_eligible=eligible,
    ))


def test_gate_promotes_only_measured_eligible_cells(tmp_path):
    store = TipValidationStore(path=str(tmp_path / "tv.duckdb"))
    _report(store, "iron_condor", "pin_low_vol", eligible=True)
    _report(store, "long_straddle", "trend_high_vol", eligible=False)
    assert decide_tier(_tip("iron_condor", "pin_low_vol"), store) == HEADLINE
    assert decide_tier(_tip("long_straddle", "trend_high_vol"), store) == WATCHLIST
    # an unknown cell (no measured evidence) is never headline
    assert decide_tier(_tip("short_strangle", "neutral"), store) == WATCHLIST
    store.close()


def test_gate_refuses_headline_when_tip_net_negative(tmp_path):
    store = TipValidationStore(path=str(tmp_path / "tv.duckdb"))
    _report(store, "iron_condor", "pin_low_vol", eligible=True)
    # cell is eligible, but THIS tip doesn't clear its own costs → watchlist
    assert decide_tier(_tip("iron_condor", "pin_low_vol", cae=-10.0), store) == WATCHLIST
    store.close()


def test_gate_without_store_is_watchlist():
    assert decide_tier(_tip(), None) == WATCHLIST
