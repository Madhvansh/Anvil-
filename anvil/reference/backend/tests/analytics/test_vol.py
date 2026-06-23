"""IV/vol analytics: ATM IV, skew sign, IV rank/percentile, smile ordering."""

from __future__ import annotations

import pytest

from oip.analytics import vol

pytestmark = [pytest.mark.unit]


def test_atm_iv_uses_atm_strike(sample_chain):
    # future 22014.5 → nearest strike 22000; call IV .124, put IV .127 → mean .1255
    assert vol.atm_iv(sample_chain) == pytest.approx((0.124 + 0.127) / 2)


def test_skew_positive_with_put_skew(wide_chain):
    s = vol.skew(wide_chain, wing_pct=0.02)
    assert s is not None and s > 0  # puts richer than calls (equity-index skew)


def test_iv_rank_and_percentile():
    hist = [0.10, 0.12, 0.14, 0.16, 0.18]
    assert vol.iv_rank(0.14, hist) == pytest.approx((0.14 - 0.10) / (0.18 - 0.10))  # 0.5
    assert vol.iv_percentile(0.15, hist) == pytest.approx(3 / 5)  # .10,.12,.14 below
    assert vol.iv_rank(0.14, [0.14]) is None     # too thin
    assert vol.iv_rank(None, hist) is None
    assert vol.iv_percentile(None, hist) is None


def test_iv_smile_sorted_and_complete(wide_chain):
    smile = vol.iv_smile(wide_chain)
    strikes = [k for k, _, _ in smile]
    assert strikes == sorted(strikes)
    assert len(smile) == 9
