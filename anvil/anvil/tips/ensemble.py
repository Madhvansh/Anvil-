"""Decorrelated ensemble + meta-label gate (Innovation I.4) — fuse orthogonal FAMILY probabilities into
ONE fused conviction without double-counting the shared vol/gamma shock, and (when trained) attach a
calibrated ACT/ABSTAIN probability from the meta-label.

Reuses ``calibration.combine`` (ZCA + decorrelated weighted mean), ``backtest.orthogonality`` (the
admission gate), and ``tips.meta_label``. Honesty rails: fusion is a DECORRELATED weighted mean of
CALIBRATED family probabilities — never a naive agreement count (which triple-counts one vol shock and
over-sizes); a new family JOINS the fused set only if it is decorrelated AND adds shrunk incremental OOF
edge; the meta-label ACT probability is shown ALONGSIDE, display/threshold only, until it clears the
locked battery (no gate circularity).
"""

from __future__ import annotations

from ..backtest.orthogonality import AdmissionVerdict, admit_signal
from ..calibration.combine import combine_calibrated


def _naive_agreement(present: dict) -> int:
    """How many families lean 'yes' (p > 0.5) — surfaced ONLY for contrast with the decorrelated fused
    number; never used to size (agreement double-counts the shared shock — the whole reason to decorrelate)."""
    return sum(1 for v in present.values() if v is not None and v > 0.5)


def fuse_families(p_by_family: dict, weights: dict | None = None, *,
                  meta=None, meta_features: dict | None = None) -> dict:
    """Fuse per-family CALIBRATED probabilities → ``{fused, n_families, families, naive_agreement}``.
    A trained ``meta`` (``tips.meta_label.MetaLabel``) + ``meta_features`` add an ``act_probability``
    ALONGSIDE (never overwriting) the fused conviction."""
    present = {k: float(v) for k, v in p_by_family.items() if v is not None}
    out = {
        "fused": combine_calibrated(p_by_family, weights),
        "n_families": len(present),
        "families": present,
        "naive_agreement": _naive_agreement(present),
    }
    if meta is not None and meta_features is not None:
        out["act_probability"] = meta.predict(meta_features)
    return out


def admit_family(candidate_returns, incumbent_returns, **kwargs) -> AdmissionVerdict:
    """A new family JOINS the fused set only if the orthogonality gate admits it (decorrelated + shrunk
    incremental OOF edge). Thin pass-through so callers fuse + admit from one place."""
    return admit_signal(candidate_returns, incumbent_returns, **kwargs)
