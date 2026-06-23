"""Phase 0 — moat-hardening regressions.

Two holes the audit found in the anti-overfit gate, with tests that fail on the old behavior:

  1. Day-blocking was applied only to the touch curve, so the OPTION/EQUITY gates counted correlated
     same-day tips as independent observations (inflating t = SR*sqrt(n) and the Deflated Sharpe).
     ``validate_cells`` now collapses every cell to one return per independent trading day.
  2. ``n_trials`` fed to the Deflated Sharpe was ``len(cells)`` — it never counted the thresholds /
     targets / horizons a researcher actually swept. ``validate_cells`` now accepts an honest
     ``n_trials`` (from the experiment registry) so a sweep RAISES the bar instead of sneaking through.
"""

from __future__ import annotations

from anvil.backtest.aggregate import new_cell, validate_cells
from anvil.backtest.trials import TrialRegistry


def _cell_from_days(day_to_returns: dict) -> dict:
    c = new_cell()
    for day, rets in day_to_returns.items():
        for r in rets:
            c["returns"].append(r)
            c["net"].append(r * 100.0)
            c["conv"].append(0.5)
            c["wins"] += int(r > 0)
            c["by_day"][day].append(r)
    return c


def test_significance_uses_independent_days_not_correlated_trades():
    """60 tips that all resolved on the SAME 3 days must score as n=3 independent days, not n=60."""
    key = ("short_strangle", "pin", "NIFTY")
    cell = _cell_from_days({
        "2025-09-01": [0.10] * 20,
        "2025-09-02": [0.12] * 20,
        "2025-09-03": [0.08] * 20,
    })
    reports, _ = validate_cells(
        {key: cell}, ["2025-09-01", "2025-09-02", "2025-09-03"], min_samples=2, n_trials=1)
    assert reports[0].n == 3  # independent trading days — NOT 60 clustered tips


def _day_level_cell(day_returns: list[float]) -> dict:
    return _cell_from_days({f"d{i:03d}": [r] for i, r in enumerate(day_returns)})


def test_more_trials_raises_the_deflated_sharpe_bar():
    """The same observed Sharpe must be deflated MORE as the number of configs tried grows — i.e. a
    threshold/target sweep can no longer pass for free. Deflated Sharpe must be monotonically lower as
    n_trials rises, by a material margin (this is the whole point of counting trials)."""
    key = ("equity_directional", "xs_momentum", "EQUITY")
    returns = [0.08] * 45 + [-0.06] * 15  # 60 independent days, genuine positive edge
    cell = _day_level_cell(returns)
    res_days = sorted(cell["by_day"].keys())

    dsrs = []
    for n_trials in (1, 100, 10_000, 1_000_000):
        reports, _ = validate_cells({key: cell}, res_days, min_samples=2, n_trials=n_trials)
        dsrs.append(reports[0].dsr)

    assert all(d == d for d in dsrs)                       # all finite (not NaN)
    assert dsrs == sorted(dsrs, reverse=True)              # strictly non-increasing in n_trials
    assert dsrs[0] > dsrs[-1] + 0.10                       # counting trials deflates by a real margin
    assert dsrs[0] != dsrs[-1]


def test_trial_registry_counts_persist(tmp_path):
    reg = TrialRegistry(path=str(tmp_path / "trials.duckdb"))
    try:
        assert reg.total("equity_xs_momentum") == 0
        assert reg.bump("equity_xs_momentum", 200) == 200      # a 200-config threshold sweep
        assert reg.bump("equity_xs_momentum", 3) == 203
        assert reg.total("equity_xs_momentum") == 203
        assert reg.total() >= 203                              # all-scope sum
    finally:
        reg.close()
