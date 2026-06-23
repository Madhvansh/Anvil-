"""Realized-vol forecast + VRP: Garman-Klass recovers a known vol and is more efficient than
close-to-close (C4); HAR/EWMA forecast lands near the true level; VRP is a resolvable probability
with the right sign and a recorded horizon (C5/C7)."""

from __future__ import annotations

import numpy as np

from anvil.engine.realized_vol_forecast import (
    har_rv_forecast,
    realized_vol_gk,
    vrp,
    vrp_ratio_for_touch,
)
from anvil.engine.vol import realized_vol


def _ohlc(sigma_ann=0.20, n_days=250, seed=0, steps=390):
    """Synthetic OHLC from an intraday GBM at known annual vol → realistic H/L for range estimators."""
    rng = np.random.default_rng(seed)
    dt = 1.0 / 252.0 / steps
    s = 100.0
    rows, closes = [], [s]
    for _ in range(n_days):
        path = [s]
        for _ in range(steps):
            s *= np.exp(-0.5 * sigma_ann**2 * dt + sigma_ann * np.sqrt(dt) * rng.standard_normal())
            path.append(s)
        rows.append((path[0], max(path), min(path), path[-1]))
        closes.append(path[-1])
    return rows, closes


def test_gk_recovers_vol():
    rows, _ = _ohlc(0.18, 300, seed=1)
    assert abs(realized_vol_gk(rows) - 0.18) < 0.035


def test_gk_lower_sampling_variance_than_close_to_close():
    # Efficiency = lower sampling variance for the same sample. Estimate a constant vol over many
    # independent short windows and compare the spread of each estimator across windows.
    rows, closes = _ohlc(0.20, 600, seed=4)
    win = 10
    gk = [realized_vol_gk(rows[i:i + win]) for i in range(0, len(rows) - win, win)]
    cc = [realized_vol(closes[i:i + win + 1]) for i in range(0, len(closes) - win - 1, win)]
    assert np.std([x for x in gk if x]) < np.std([x for x in cc if x])


def test_har_forecast_near_level():
    rows, _ = _ohlc(0.22, 260, seed=2)
    f = har_rv_forecast(rows, horizon=5)
    assert f["method"] in ("har_rv", "ewma", "trailing_gk")
    assert f["e_rv"] is not None and abs(f["e_rv"] - 0.22) < 0.06
    assert f["horizon"] == 5


def test_vrp_probability_sign_and_horizon():
    rich = vrp(0.30, 0.15, log_rv_std=0.3, horizon=5)
    cheap = vrp(0.12, 0.20, log_rv_std=0.3, horizon=5)
    assert rich["prob_realized_lt_implied"] > 0.5 and rich["richness"] == "rich"
    assert cheap["prob_realized_lt_implied"] < 0.5 and cheap["richness"] == "cheap"
    assert vrp(0.2, 0.2, horizon=7)["horizon"] == 7


def test_vrp_ratio_for_touch():
    assert abs(vrp_ratio_for_touch(0.20, 0.16) - 0.8) < 1e-9
    assert vrp_ratio_for_touch(None, 0.1) is None
