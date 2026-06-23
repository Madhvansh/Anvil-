"""Phase 0 — the gate honours a green verdict only if the CURRENT gate certified it.

A stored ``headline_eligible`` row carries the ``model_version`` of the gate that wrote it. When the
gate's inputs/logic move on (a Phase bump), an old green is stale and must be demoted to the watchlist
rather than trusted forever. Legacy/hand-seeded rows with no stamp stay version-agnostic (not demoted
on that basis), so existing seeded-cell tests keep working.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from anvil.tips.gate import decide_tier
from anvil.tips.store import GATE_VERSION
from anvil.tips.types import HEADLINE, WATCHLIST

_IST = timezone(timedelta(hours=5, minutes=30))
_NOW = datetime(2026, 6, 22, 12, 0, tzinfo=_IST)


class _Store:
    def __init__(self, report):
        self._r = report

    def get(self, *_args):
        return self._r


def _tip():
    return SimpleNamespace(
        cost_adjusted_ev=0.05, structure="short_strangle", regime_bucket="pin", underlying="NIFTY")


def test_current_version_verdict_headlines():
    rep = {"headline_eligible": True, "model_version": GATE_VERSION}
    assert decide_tier(_tip(), _Store(rep)) == HEADLINE


def test_stale_version_verdict_is_demoted():
    rep = {"headline_eligible": True, "model_version": "phase0-0.0.1"}
    assert decide_tier(_tip(), _Store(rep)) == WATCHLIST


def test_unstamped_legacy_verdict_is_honored():
    assert decide_tier(_tip(), _Store({"headline_eligible": True, "model_version": None})) == HEADLINE
    assert decide_tier(_tip(), _Store({"headline_eligible": True})) == HEADLINE  # no column at all


def test_costs_must_clear_regardless_of_version():
    tip = SimpleNamespace(
        cost_adjusted_ev=-0.01, structure="short_strangle", regime_bucket="pin", underlying="NIFTY")
    rep = {"headline_eligible": True, "model_version": GATE_VERSION}
    assert decide_tier(tip, _Store(rep)) == WATCHLIST


# ---- staleness (gate_max_stale_days, default 30) ----
def _fresh_rep(days_old):
    return {"headline_eligible": True, "model_version": GATE_VERSION,
            "updated_ts": (_NOW - timedelta(days=days_old)).isoformat()}


def test_fresh_verdict_headlines():
    assert decide_tier(_tip(), _Store(_fresh_rep(5)), now=_NOW) == HEADLINE


def test_stale_verdict_is_demoted():
    assert decide_tier(_tip(), _Store(_fresh_rep(45)), now=_NOW) == WATCHLIST  # > 30 days → stale


def test_empty_or_unparseable_updated_ts_skips_staleness():
    for ts in ("", None, "not-a-date"):
        rep = {"headline_eligible": True, "model_version": GATE_VERSION, "updated_ts": ts}
        assert decide_tier(_tip(), _Store(rep), now=_NOW) == HEADLINE


def test_custom_max_stale_days_overrides_default():
    rep = _fresh_rep(10)
    assert decide_tier(_tip(), _Store(rep), now=_NOW, max_stale_days=7) == WATCHLIST
    assert decide_tier(_tip(), _Store(rep), now=_NOW, max_stale_days=30) == HEADLINE
