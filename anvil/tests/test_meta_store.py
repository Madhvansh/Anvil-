"""Tests for meta-label persistence + the cached loader (Innovation I.4 connector)."""

from __future__ import annotations

from anvil.tips import meta_store as ms
from anvil.tips.meta_features import FEATURE_NAMES, features_from
from anvil.tips.meta_label import MetaLabel


def _trained_meta():
    rows = []
    for i in range(160):
        mom = i % 2
        rows.append({**features_from(0.75 if mom else 0.4,
                                     (["mtf_trend"] if mom else ["smart_money_block"]), "neutral"),
                     "correct": float(mom)})
    ml = MetaLabel.train(rows, FEATURE_NAMES)
    assert ml is not None
    return ml


def test_save_load_roundtrip_predicts_identically(tmp_path):
    ml = _trained_meta()
    path = str(tmp_path / "meta.json")
    ms.save(ml, path)
    loaded = ms.load(path)
    assert loaded is not None and loaded.feature_names == FEATURE_NAMES and loaded.n == 160
    feats = features_from(0.75, ["mtf_trend"], "neutral")
    assert abs(loaded.predict(feats) - ml.predict(feats)) < 1e-9   # exact reconstruction


def test_load_missing_returns_none(tmp_path):
    assert ms.load(str(tmp_path / "nope.json")) is None


def test_get_meta_label_caches_and_refreshes(tmp_path):
    path = str(tmp_path / "meta.json")
    assert ms.get_meta_label(path) is None         # nothing persisted yet → abstain
    ms.save(_trained_meta(), path)
    ms.refresh_cache()
    got = ms.get_meta_label(path)
    assert got is not None and got.n == 160
