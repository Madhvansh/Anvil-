"""Tip outcome resolution: target-before-stop within horizon, and the P&L shortcut."""

from anvil.tips.resolve import resolve_outcome_from_path, resolve_outcome_from_pnl


def test_pnl_route():
    assert resolve_outcome_from_pnl(10.0) == 1
    assert resolve_outcome_from_pnl(-1.0) == 0
    assert resolve_outcome_from_pnl(0.0) == 0


def test_target_hit_first_is_a_win():
    ev, why = resolve_outcome_from_path(100, target=110, stop=95, marks=[101, 105, 111, 90])
    assert (ev, why) == (1, "target")


def test_stop_hit_first_is_a_loss():
    ev, why = resolve_outcome_from_path(100, target=110, stop=95, marks=[99, 94, 111])
    assert (ev, why) == (0, "stop")


def test_timeout_resolves_on_final_vs_entry():
    win, _ = resolve_outcome_from_path(100, target=120, stop=80, marks=[101, 103, 102])
    assert win == 1
    loss, _ = resolve_outcome_from_path(100, target=120, stop=80, marks=[99, 98, 97])
    assert loss == 0


def test_bearish_direction_inverts():
    # higher_is_win=False: a bearish trade wins when the mark falls to target.
    ev, why = resolve_outcome_from_path(100, target=90, stop=105, marks=[98, 92, 89], higher_is_win=False)
    assert (ev, why) == (1, "target")


def test_empty_path_is_no_win():
    assert resolve_outcome_from_path(100, 110, 95, marks=[]) == (0, "no_path")
