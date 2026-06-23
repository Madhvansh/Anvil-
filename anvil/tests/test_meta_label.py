"""Tests for the meta-label (pure-numpy logistic, OOF, abstain-safe)."""

from __future__ import annotations

import numpy as np

from anvil.tips.meta_label import LogisticModel, MetaLabel, oof_probabilities


def test_logistic_learns_separable():
    rng = np.random.default_rng(0)
    X = rng.standard_normal((200, 1))
    y = (X[:, 0] > 0).astype(float)
    m = LogisticModel(l2=0.1).fit(X, y)
    assert m.predict_proba(np.array([[2.5]]))[0] > 0.8
    assert m.predict_proba(np.array([[-2.5]]))[0] < 0.2


def test_oof_probabilities_shape_and_none():
    rng = np.random.default_rng(1)
    X = rng.standard_normal((100, 2))
    y = (X[:, 0] + X[:, 1] > 0).astype(float)
    oof = oof_probabilities(X, y, k=5)
    assert oof is not None and oof.shape == (100,) and np.all((oof >= 0) & (oof <= 1))
    assert oof_probabilities(X[:4], y[:4], k=5) is None       # too few for 5 folds


def test_metalabel_train_and_predict_ranks_by_quality():
    rng = np.random.default_rng(2)
    rows = []
    for _ in range(240):
        agree = float(rng.integers(0, 4))
        strength = float(rng.random())
        prob = 1.0 / (1.0 + np.exp(-(agree - 1.5))) * 0.5 + strength * 0.4
        rows.append({"agreement": agree, "strength": strength, "correct": float(rng.random() < prob)})
    ml = MetaLabel.train(rows, ["agreement", "strength"])
    assert ml is not None and ml.n == 240
    p_hi = ml.predict({"agreement": 3.0, "strength": 0.9})
    p_lo = ml.predict({"agreement": 0.0, "strength": 0.05})
    assert p_hi is not None and 0.0 <= p_hi <= 1.0 and p_hi > p_lo   # better setups → higher ACT prob


def test_metalabel_abstains_thin_or_single_class():
    assert MetaLabel.train([{"a": 1.0, "correct": 1.0}] * 10, ["a"], min_samples=60) is None
    single = [{"a": float(i), "correct": 1.0} for i in range(80)]
    assert MetaLabel.train(single, ["a"]) is None              # only one outcome → can't meta-label
