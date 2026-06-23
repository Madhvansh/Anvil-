"""Phase 0 — purged walk-forward OUT-OF-FOLD edge is part of certification.

``combinatorial_purged_splits`` / ``purged_walk_forward_splits`` existed in ``validation`` but were
never called by the gate — leak-safety rested on ``AsOfContext`` alone. Eligibility now requires the
edge to HOLD out-of-fold (mean forward-block edge > 0), so a cell whose positive grand mean came from
one contiguous early window — the block the gate only ever trains on — fails even though ``edge > 0``.
"""

from __future__ import annotations

from anvil.backtest.aggregate import cpcv_oof_edge


def test_persistent_edge_holds_out_of_fold():
    assert cpcv_oof_edge([0.05] * 40, embargo=1) > 0


def test_edge_in_one_contiguous_block_fails_oof():
    # All the edge sits in the FIRST block (walk-forward only ever TRAINS on it); the forward
    # out-of-fold blocks don't hold it, so OOF edge ≤ 0 even though the grand mean is positive.
    series = [0.20] * 8 + [-0.01] * 32
    assert (sum(series) / len(series)) > 0           # clears the plain edge>0 term
    assert cpcv_oof_edge(series, embargo=1) <= 0      # ...but fails OOF certification


def test_front_loaded_edge_fails_oof():
    assert cpcv_oof_edge([0.10] * 20 + [-0.08] * 20, embargo=1) <= 0


def test_embargo_is_honored_without_crashing():
    # A larger embargo purges more train rows (and may drop the earliest fold); the OOF edge survives.
    assert cpcv_oof_edge([0.05] * 40, embargo=8) > 0


def test_too_few_days_is_nan():
    v = cpcv_oof_edge([0.1, 0.2, 0.3], embargo=1)
    assert v != v  # NaN → the gate treats it as a fail
