"""Phase 5 — coverage logging (IssuedTipStore.tip_coverage): the honest 'how often the engine
speaks vs abstains' dial. Live path is additive (a session's speak rate); EOD path REPLACEs (re-running
a day overwrites, never inflates)."""

from anvil.tips.store import IssuedTipStore


def test_coverage_additive_and_rolling(tmp_path):
    s = IssuedTipStore(str(tmp_path / "cov.duckdb"))
    try:
        s.bump_coverage("2026-06-20", "NIFTY", "tip_live", spoke=True, actionable=True, watch=False,
                        headline=True, conviction=0.7)
        s.bump_coverage("2026-06-20", "NIFTY", "tip_live", spoke=True, actionable=True, watch=True,
                        headline=False, conviction=0.6)
        s.bump_coverage("2026-06-20", "NIFTY", "tip_live", spoke=False, actionable=False, watch=False,
                        headline=False, conviction=None)
        roll = s.coverage_rolling(n_days=20)
        assert roll["passes"] == 3
        assert roll["coverage_pct"] == round(2 / 3, 4)
        assert abs(roll["mean_conviction_when_spoke"] - 0.65) < 1e-6
    finally:
        s.close()


def test_set_coverage_day_idempotent(tmp_path):
    s = IssuedTipStore(str(tmp_path / "cov2.duckdb"))
    try:
        for _ in range(2):  # re-running a day must overwrite, not double-count
            s.set_coverage_day("2026-06-20", "NIFTY", "tip_live", passes=5, actionable=2, watch=1,
                               abstain=2, headline=1, conviction_sum=1.3, spoke=3)
        roll = s.coverage_rolling()
        assert roll["passes"] == 5
        assert roll["coverage_pct"] == round(3 / 5, 4)
    finally:
        s.close()


def test_coverage_rolling_empty(tmp_path):
    s = IssuedTipStore(str(tmp_path / "cov3.duckdb"))
    try:
        assert s.coverage_rolling()["days"] == 0
    finally:
        s.close()
