"""predict_for_chain attaches the meta-label ACT probability (display-only, abstain-safe)."""

from __future__ import annotations

from anvil.ingest import get_connector
from anvil.tips.meta_features import FEATURE_NAMES
from anvil.tips.predict import predict_for_chain


def _chain():
    return get_connector("demo").get_chain("NIFTY")


class _StubMeta:
    """A meta-label stub: predicts a fixed probability, recording the features it was queried with."""

    def __init__(self, p):
        self.p = p
        self.seen = None

    def predict(self, features):
        self.seen = features
        return self.p


def test_no_meta_label_means_act_probability_none():
    _ctx, _b, _s, pred, _t = predict_for_chain(_chain(), source="tip_live", equity=1_000_000.0)
    assert pred.act_probability is None
    assert pred.to_dict()["act_probability"] is None     # public schema carries the key


def test_meta_label_attached_and_features_well_formed():
    meta = _StubMeta(0.123456)
    _ctx, _b, _s, pred, _t = predict_for_chain(
        _chain(), source="tip_live", equity=1_000_000.0, meta_label=meta)
    assert pred.act_probability == 0.1235               # rounded, attached
    assert pred.to_dict()["act_probability"] == 0.1235  # public-safe (display analytics)
    assert set(meta.seen) == set(FEATURE_NAMES)         # extractor produced the stable feature set


def test_meta_label_none_prediction_survives():
    class _Abstain:
        def predict(self, features):
            return None

    _ctx, _b, _s, pred, _t = predict_for_chain(
        _chain(), source="tip_live", equity=1_000_000.0, meta_label=_Abstain())
    assert pred.act_probability is None                 # abstain → None, prediction still built
