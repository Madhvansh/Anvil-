"""Tests for the decorrelated ensemble fusion + family admission (Innovation I.4)."""

from __future__ import annotations

import numpy as np

from anvil.tips.ensemble import admit_family, fuse_families
from anvil.tips.meta_label import MetaLabel


def test_fuse_families_decorrelated_mean_drops_none():
    out = fuse_families({"momentum": 0.7, "vrp": 0.6, "dealer": None})
    assert out["n_families"] == 2 and abs(out["fused"] - 0.65) < 1e-9
    assert out["naive_agreement"] == 2 and "dealer" not in out["families"]


def test_fuse_families_weighted():
    out = fuse_families({"a": 0.8, "b": 0.4}, {"a": 3.0, "b": 1.0})
    assert abs(out["fused"] - (3 * 0.8 + 1 * 0.4) / 4) < 1e-9


def test_fuse_families_with_meta_act_probability():
    rows = [{"x": float(i % 2), "correct": float(i % 2)} for i in range(80)]
    ml = MetaLabel.train(rows, ["x"])
    out = fuse_families({"a": 0.6}, meta=ml, meta_features={"x": 1.0})
    assert "act_probability" in out and 0.0 <= out["act_probability"] <= 1.0


def test_admit_family_decorrelated_admitted_duplicate_rejected():
    rng = np.random.default_rng(0)
    incumbent = rng.standard_normal(200)
    independent = rng.standard_normal(200)
    near_duplicate = incumbent + 0.01 * rng.standard_normal(200)
    assert admit_family(independent, [incumbent]).admit is True
    v = admit_family(near_duplicate, [incumbent])
    assert v.admit is False and v.max_corr > 0.9
