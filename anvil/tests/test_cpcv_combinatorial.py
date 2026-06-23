"""Phase 3 — combinatorial purged CV is now EXERCISED in certification (was defined, never called).

``cpcv_oof_edge_combinatorial`` holds out every C(n_groups, n_test_groups) combination and gates on the
MEDIAN path edge, so an edge must survive a MAJORITY of held-out combinations — strictly more paths than
the walk-forward forward folds. ``validate_cells`` now requires BOTH OOF checks to be positive.
"""

from __future__ import annotations

from anvil.backtest.aggregate import (
    cpcv_oof_edge,
    cpcv_oof_edge_combinatorial,
    new_cell,
    validate_cells,
)


def test_spread_edge_holds_across_combinatorial_paths():
    assert cpcv_oof_edge_combinatorial([0.05] * 40, embargo=1) > 0


def test_edge_in_one_group_fails_majority_of_paths():
    # Edge concentrated in the first group: only the few paths that test it look good, so a MAJORITY of
    # the C(6,2) held-out combinations are negative → the median falls ≤ 0.
    series = [0.20] * 7 + [-0.02] * 33
    assert (sum(series) / len(series)) > 0          # clears the plain edge>0 term (positive grand mean)
    assert cpcv_oof_edge_combinatorial(series, embargo=1) <= 0


def test_too_few_days_is_nan():
    v = cpcv_oof_edge_combinatorial([0.1, 0.2, 0.3], embargo=1)
    assert v != v  # NaN → the gate treats it as a fail


def test_combinatorial_rejects_what_walk_forward_misses():
    """The whole point of ADDING the combinatorial check: it rejects a cell whose walk-forward OOF edge
    is positive (forward folds all hold) but whose edge is absent from a MAJORITY of CPCV groups."""
    series = [-0.3] * 6 + [0.15] * 24 + [-0.3] * 6
    assert cpcv_oof_edge(series, embargo=0) > 0                  # walk-forward says OK
    assert cpcv_oof_edge_combinatorial(series, embargo=0) <= 0   # ...combinatorial catches it


def _day_cell(returns: list[float]) -> dict:
    c = new_cell()
    for i, r in enumerate(returns):
        d = f"d{i:03d}"
        c["returns"].append(r)
        c["net"].append(r * 100.0)
        c["conv"].append(0.5)
        c["wins"] += int(r > 0)
        c["by_day"][d].append(r)
    return c


def test_validate_cells_uses_the_combinatorial_check():
    """End-to-end: a cell that passes walk-forward but fails combinatorial is NOT headline-eligible —
    proving the new condition is wired into the gate, not just defined."""
    key = ("short_strangle", "pin", "NIFTY")
    cell = _day_cell([-0.3] * 6 + [0.15] * 24 + [-0.3] * 6)
    res_days = sorted(cell["by_day"].keys())
    reports, _ = validate_cells({key: cell}, res_days, min_samples=2, n_trials=1, embargo=0)
    assert reports[0].headline_eligible is False
