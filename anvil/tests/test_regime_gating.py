"""Regime gate: classify the tape and mask wrong-regime factors so they can't count toward a tip."""

from anvil.factors import (
    EVENT_CRUSH,
    NEUTRAL_REGIME,
    PIN_LOW_VOL,
    TREND_HIGH_VOL,
    apply_regime_mask,
    classify_regime,
)
from anvil.factors.base import STRONG, FactorSignal
from anvil.ingest.demo import build_demo_chain
from anvil.strategy import SignalContext
from anvil.strategy.types import BEARISH, BULLISH, LONG_VOL, NEUTRAL, SHORT_VOL


def _sig(direction):
    return FactorSignal("f_" + direction or "f", True, 0.8, direction, STRONG, {})


def test_classify_returns_a_valid_bucket_on_demo():
    ctx = SignalContext(build_demo_chain("NIFTY", spot=24000.0))
    assert classify_regime(ctx) in (PIN_LOW_VOL, TREND_HIGH_VOL, EVENT_CRUSH, NEUTRAL_REGIME)


def test_trend_regime_masks_premium_selling():
    sigs = [_sig(SHORT_VOL), _sig(LONG_VOL), _sig(NEUTRAL)]
    apply_regime_mask(sigs, TREND_HIGH_VOL)
    by_dir = {s.direction: s for s in sigs}
    assert by_dir[SHORT_VOL].regime_mask is False and by_dir[SHORT_VOL].active is False
    assert by_dir[LONG_VOL].regime_mask is True and by_dir[LONG_VOL].active is True


def test_pin_regime_masks_long_vol():
    sigs = [_sig(SHORT_VOL), _sig(LONG_VOL)]
    apply_regime_mask(sigs, PIN_LOW_VOL)
    by_dir = {s.direction: s for s in sigs}
    assert by_dir[LONG_VOL].regime_mask is False
    assert by_dir[SHORT_VOL].regime_mask is True


def test_event_crush_masks_direction_and_long_vol_but_keeps_short_vol():
    sigs = [_sig(BULLISH), _sig(BEARISH), _sig(LONG_VOL), _sig(SHORT_VOL)]
    apply_regime_mask(sigs, EVENT_CRUSH)
    by_dir = {s.direction: s for s in sigs}
    assert by_dir[BULLISH].regime_mask is False
    assert by_dir[BEARISH].regime_mask is False
    assert by_dir[LONG_VOL].regime_mask is False
    assert by_dir[SHORT_VOL].regime_mask is True  # fading premium into the crush is allowed


def test_neutral_regime_masks_nothing():
    sigs = [_sig(SHORT_VOL), _sig(LONG_VOL), _sig(BULLISH)]
    apply_regime_mask(sigs, NEUTRAL_REGIME)
    assert all(s.regime_mask for s in sigs)
