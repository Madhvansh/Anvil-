"""Phase 0 — a lone-member family is deflated by a CONSERVATIVE cross-trial variance, not the
optimistic 1/(n-1) single-Sharpe sampling variance (which would over-certify a solitary cell)."""

from __future__ import annotations

from anvil.backtest import aggregate as agg
from anvil.backtest import validation as val
from anvil.backtest.aggregate import new_cell, validate_cells


def _day_cell(returns):
    c = new_cell()
    for i, r in enumerate(returns):
        d = f"d{i:03d}"
        c["returns"].append(r)
        c["net"].append(r * 100.0)
        c["conv"].append(0.5)
        c["wins"] += int(r > 0)
        c["by_day"][d].append(r)
    return c


def test_singleton_family_uses_conservative_variance_not_optimistic_floor():
    returns = [0.08] * 45 + [-0.06] * 15  # 60 independent days, genuine positive edge
    cell = _day_cell(returns)
    res_days = sorted(cell["by_day"].keys())
    reports, _ = validate_cells({("solo", "b", "NIFTY"): cell}, res_days, min_samples=2, n_trials=100)
    dsr_gate = reports[0].dsr

    sr = val.sharpe_ratio(returns)  # day-blocked series == returns (one per day)
    dsr_conservative = round(val.deflated_sharpe_ratio(
        sr, n_trials=100, n_obs=60, sr_variance=agg._SINGLETON_SR_VARIANCE), 4)
    dsr_optimistic = round(val.deflated_sharpe_ratio(
        sr, n_trials=100, n_obs=60, sr_variance=1.0 / 59), 4)

    assert dsr_gate == dsr_conservative   # the gate used the conservative singleton variance…
    assert dsr_gate < dsr_optimistic      # …which deflates HARDER than the optimistic 1/(n-1) floor
