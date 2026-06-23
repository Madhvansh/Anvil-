"""Meta-label feature extraction (Innovation I.4 glue) — turn a tip/prediction's fired signals +
conviction + regime into the stable feature vector the meta-label trains on / predicts from, and build
the training set from resolved tips.

Honesty: the features are descriptors of the PRIMARY call available at issue time (no future info); the
training label is the realized binary outcome. Family flags are ORTHOGONAL groupings of factor names —
so the meta-label learns *which combinations of independent edge sources* actually convert, which is the
honest lever on accuracy-when-it-speaks. Training is OOF inside ``MetaLabel`` and abstains until enough
resolved labels accrue, so cold-start emits nothing.
"""

from __future__ import annotations

from .meta_label import MetaLabel

# Orthogonal family groupings of factor names → one flag each (decorrelated edge sources).
_FAMILIES = {
    "f_momentum": {"mtf_trend", "intraday_or_vwap", "expiry_last30_gamma"},
    "f_flow": {"oi_velocity_thrust", "gex_flip_momentum", "iv_rank_velocity"},
    "f_dealer": {"gamma_flip_sr", "charm_pin", "vanna_drift"},
    "f_chain": {"skew_slope_extreme", "oi_change_thrust", "smart_money_block", "zero_dte_dynamics"},
}
_REGIMES = ["pin_low_vol", "trend_high_vol", "event_crush", "neutral"]

# Stable, ordered feature list the model is trained + queried with (order is irrelevant to MetaLabel,
# which keys by name, but kept fixed for reproducibility).
FEATURE_NAMES = ["conviction", "n_signals", *list(_FAMILIES.keys()), *(f"r_{r}" for r in _REGIMES)]


def features_from(conviction, signals_fired, regime_bucket: str) -> dict:
    """Build the feature dict from a call's conviction + fired-signal names + regime bucket."""
    fired = set(signals_fired or [])
    feats = {"conviction": float(conviction or 0.0), "n_signals": float(len(fired))}
    for fam, names in _FAMILIES.items():
        feats[fam] = 1.0 if (fired & names) else 0.0
    for r in _REGIMES:
        feats[f"r_{r}"] = 1.0 if regime_bucket == r else 0.0
    return feats


def features_from_payload(payload: dict) -> dict:
    return features_from(payload.get("conviction"), payload.get("signals_fired"),
                         payload.get("regime_bucket", ""))


def training_rows(istore, sources: tuple[str, ...] = ("tip_live",)) -> list[dict]:
    """Resolved-tip rows as ``{**features, "correct": outcome}`` for ``MetaLabel.train``."""
    rows: list[dict] = []
    for payload, outcome in istore.resolved_payloads(sources):
        feats = features_from_payload(payload)
        feats["correct"] = float(outcome)
        rows.append(feats)
    return rows


def train_from_store(istore, sources: tuple[str, ...] = ("tip_live",), *, min_samples: int = 60):
    """Train a ``MetaLabel`` from a store's resolved history; None until enough labels (cold-start safe)."""
    return MetaLabel.train(training_rows(istore, sources), FEATURE_NAMES, min_samples=min_samples)
