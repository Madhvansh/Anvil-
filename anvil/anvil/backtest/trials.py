"""Experiment / trial registry — the honest denominator for the Deflated Sharpe.

The Deflated Sharpe Ratio must discount for the number of strategy configurations actually evaluated
against the data (López de Prado: the expected max Sharpe of N trials on a true martingale is > 0 and
grows with sqrt(2*ln N)). Counting only the cells that *materialized* in one run (``len(cells)``)
ignores every threshold / target / horizon / feature sweep the researcher tried and threw away — the
real overfitting channel. This registry persists a monotonically-increasing count of trials per
experiment scope so ``validate_cells(..., n_trials=registry.total(scope))`` raises the bar honestly.

Discipline: bump the registry ONCE per distinct configuration evaluated (a sweep of 200 thresholds is
200 trials), keyed by a stable scope string (e.g. ``"equity_xs_momentum"``). It is deliberately cheap
and append-only; under-counting is the failure mode to avoid, so when in doubt, bump."""

from __future__ import annotations

import duckdb

from ..config import SETTINGS

_SCHEMA = """
CREATE TABLE IF NOT EXISTS experiment_trials (
    scope VARCHAR PRIMARY KEY,
    count BIGINT
);
"""


class TrialRegistry:
    """Persisted count of strategy configurations evaluated against the data, per scope.

    >>> reg = TrialRegistry()
    >>> reg.bump("equity_xs_momentum", 200)   # a 200-config threshold sweep
    >>> reg.total("equity_xs_momentum")        # -> 200, fed to validate_cells(n_trials=...)
    """

    def __init__(self, path: str | None = None):
        self.path = path or SETTINGS.store_path
        self.con = duckdb.connect(self.path)
        self.con.execute(_SCHEMA)

    def bump(self, scope: str, n: int = 1) -> int:
        """Add ``n`` trials to ``scope`` (idempotent-safe upsert). Returns the new total."""
        self.con.execute(
            "INSERT INTO experiment_trials (scope, count) VALUES (?, ?) "
            "ON CONFLICT (scope) DO UPDATE SET count = experiment_trials.count + ?",
            [scope, int(n), int(n)],
        )
        return self.total(scope)

    def total(self, scope: str | None = None) -> int:
        """Trials logged for ``scope`` (or across ALL scopes when ``scope`` is None). 0 if unseen."""
        if scope is None:
            row = self.con.execute("SELECT COALESCE(SUM(count), 0) FROM experiment_trials").fetchone()
        else:
            row = self.con.execute(
                "SELECT count FROM experiment_trials WHERE scope=?", [scope]).fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    def close(self) -> None:
        self.con.close()
