"""The validation spine must actually defend against overfitting/multiple-testing — these tests
lock the core guarantees: no train/test leakage, multiple-testing deflation, and a working PBO."""

import numpy as np

from anvil.backtest.validation import (
    HARVEY_T_HURDLE,
    combinatorial_purged_splits,
    deflated_sharpe_ratio,
    expected_max_sharpe_ratio,
    passes_t_hurdle,
    probabilistic_sharpe_ratio,
    probability_of_backtest_overfitting,
    purged_walk_forward_splits,
    sharpe_ratio,
    t_stat,
)


def test_sharpe_and_tstat_basic():
    r = np.full(64, 0.01)  # constant positive → infinite Sharpe (zero std) → NaN by convention
    assert np.isnan(sharpe_ratio(r))
    rng = np.random.default_rng(0)
    r = 0.001 + 0.01 * rng.standard_normal(500)
    sr, t = sharpe_ratio(r), t_stat(r)
    assert np.isfinite(sr) and np.isfinite(t)
    assert abs(t - sr * np.sqrt(500)) < 1e-9


def test_t_hurdle_is_three():
    assert HARVEY_T_HURDLE == 3.0
    assert passes_t_hurdle(3.1)
    assert passes_t_hurdle(-3.5)  # magnitude
    assert not passes_t_hurdle(2.5)


def test_cpcv_no_leakage_and_count():
    n, g, k, emb = 120, 6, 2, 3
    splits = combinatorial_purged_splits(n, n_groups=g, n_test_groups=k, embargo=emb)
    # C(6,2) = 15 partitions
    assert len(splits) == 15
    for train, test in splits:
        ts = set(test)
        # disjoint
        assert ts.isdisjoint(train)
        # embargo: every train idx is strictly farther than `emb` from every test idx
        t = np.asarray(test)
        for i in train:
            assert int(np.abs(t - i).min()) > emb


def test_walk_forward_train_precedes_test_with_embargo():
    splits = purged_walk_forward_splits(100, n_splits=5, embargo=2)
    assert splits
    for train, test in splits:
        assert max(train) < min(test)            # train strictly before test
        assert min(test) - max(train) > 2        # embargo gap respected


def test_psr_and_dsr_order_sensibly():
    # A strong per-period Sharpe over a long sample → high PSR vs 0 benchmark.
    psr = probabilistic_sharpe_ratio(0.20, 0.0, n_obs=500)
    assert 0.9 < psr <= 1.0
    # Multiple-testing deflation: the more trials, the higher the bar, the lower the DSR.
    dsr_few = deflated_sharpe_ratio(0.20, n_trials=5, n_obs=500, sr_variance=0.01)
    dsr_many = deflated_sharpe_ratio(0.20, n_trials=500, n_obs=500, sr_variance=0.01)
    assert dsr_few > dsr_many
    # E[max Sharpe] grows with the number of trials.
    assert expected_max_sharpe_ratio(500, 0.01) > expected_max_sharpe_ratio(5, 0.01)
    assert expected_max_sharpe_ratio(1, 0.01) == 0.0  # no inflation for a single trial


def test_pbo_low_for_a_genuinely_dominant_config():
    # Column 0 is consistently best in every period → never overfit → PBO ~ 0.
    rng = np.random.default_rng(1)
    T, N = 240, 10
    M = 0.001 * rng.standard_normal((T, N))
    M[:, 0] += 0.02  # a real, persistent edge
    pbo = probability_of_backtest_overfitting(M, n_splits=8)
    assert 0.0 <= pbo <= 0.1


def test_pbo_is_a_valid_probability_for_pure_noise():
    rng = np.random.default_rng(2)
    M = rng.standard_normal((240, 12))  # no real edge anywhere
    pbo = probability_of_backtest_overfitting(M, n_splits=8)
    assert 0.0 <= pbo <= 1.0
    assert np.isfinite(pbo)


def test_pbo_guards_small_input():
    assert np.isnan(probability_of_backtest_overfitting(np.zeros((4, 1)), n_splits=8))
