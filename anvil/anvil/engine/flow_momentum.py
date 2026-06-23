"""Options-flow momentum — the *velocity* of the chain, pure-numpy.

Anvil already reads the chain's STATE (GEX, OI walls, IV rank, term structure). This module reads how
that state is *moving* over recorded snapshots — the bridge from the unbuyable intraday OI/IV history
(``live.recorder`` → ``SnapshotStore``) into tradeable momentum:

- **OI velocity** — is open interest building or unwinding, and how fast?
- **GEX velocity / flip** — is dealer gamma rising, falling, or crossing zero (regime change)?
- **IV-rank velocity** — is implied vol getting richer or cheaper?
- **term-spread velocity** — is backwardation steepening (event intensifying) or flattening?

Honesty rails: every reading **abstains** (returns None) on < 2 observations, reports a vol-normalized
slope (an agreement/velocity number, never an accuracy %), and leaves thresholds to the config-backed
factors so the gate certifies them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# Direction tags — string-identical to ``anvil.strategy.types`` (engine tier stays strategy-free).
NEUTRAL = "neutral"
BULLISH = "bullish"
BEARISH = "bearish"
LONG_VOL = "long_vol"
SHORT_VOL = "short_vol"


def _clean(series) -> np.ndarray:
    a = np.asarray(series, dtype=float)
    return a[a == a]


def _slope_per_step(series) -> float | None:
    """OLS slope of ``series`` vs its index (change per step). None if < 2 points."""
    y = _clean(series)
    if y.size < 2:
        return None
    x = np.arange(y.size, dtype=float)
    x -= x.mean()
    denom = float(np.sum(x * x))
    if denom == 0:
        return None
    return float(np.sum(x * (y - y.mean())) / denom)


def _pct_change(series) -> float | None:
    """Fractional change from first to last observation. None if < 2 points or base ≤ 0."""
    y = _clean(series)
    if y.size < 2 or y[0] == 0:
        return None
    return float(y[-1] / y[0] - 1.0)


def oi_velocity(oi_series, *, rel_threshold: float = 0.05) -> dict | None:
    """Total-OI buildup velocity. Rising OI = positions building; falling = unwinding.

    Returns slope (OI/step), fractional change, and a fired/strength read. Direction here is VOL-style
    (LONG_VOL when OI builds fast = fresh positioning; NEUTRAL otherwise) — the *directional* read comes
    from price×OI in ``factors`` / ``engine.oi``; this is the pace of participation.
    """
    y = _clean(oi_series)
    if y.size < 2:
        return None
    slope = _slope_per_step(y)
    change = _pct_change(y)
    fired = change is not None and abs(change) >= rel_threshold
    strength = round(min(1.0, abs(change) / (rel_threshold * 4.0)), 4) if (fired and change) else 0.0
    return {
        "slope": slope,
        "change": change,
        "building": bool(change is not None and change > 0),
        "fired": fired,
        "strength": strength,
    }


def gex_velocity(gex_series, *, zero_cross_window: int = 3) -> dict | None:
    """Dealer-gamma velocity + zero-gamma FLIP detection.

    A sign change in GEX over the recent window = regime flip (pinning ↔ trending) — the most
    actionable flow event. ``direction`` is volatility-regime: crossing into NEGATIVE gamma →
    LONG_VOL (trend-amplifying); into POSITIVE → SHORT_VOL (mean-reverting/pinning).
    """
    y = _clean(gex_series)
    if y.size < 2:
        return None
    slope = _slope_per_step(y)
    recent = y[-zero_cross_window:] if y.size >= zero_cross_window else y
    crossed = bool(np.any(np.sign(recent[:-1]) != np.sign(recent[1:])) and recent[0] != 0)
    now_negative = bool(y[-1] < 0)
    if crossed:
        direction = LONG_VOL if now_negative else SHORT_VOL
    else:
        direction = NEUTRAL
    return {
        "slope": slope,
        "flip": crossed,
        "now_negative_gamma": now_negative,
        "direction": direction,
        "fired": crossed,
        "strength": 1.0 if crossed else round(min(1.0, abs(slope) / (abs(y).mean() + 1e-9)), 4)
        if slope is not None else 0.0,
    }


def iv_rank_velocity(iv_rank_series, *, threshold: float = 8.0) -> dict | None:
    """IV-rank velocity (points/step). Rising IV-rank = premium getting richer (favors sellers);
    falling = cheaper (favors buyers). ``threshold`` is in IV-rank points over the window."""
    y = _clean(iv_rank_series)
    if y.size < 2:
        return None
    slope = _slope_per_step(y)
    total = float(y[-1] - y[0])
    fired = abs(total) >= threshold
    if not fired:
        direction = NEUTRAL
    else:
        direction = SHORT_VOL if total > 0 else LONG_VOL   # richer → sell vol; cheaper → buy vol
    strength = round(min(1.0, abs(total) / (threshold * 4.0)), 4) if fired else 0.0
    return {"slope": slope, "change_points": total, "direction": direction,
            "fired": fired, "strength": strength}


def term_spread_velocity(front_minus_back_series, *, threshold: float = 0.01) -> dict | None:
    """Velocity of the front-minus-back ATM-IV spread. Positive spread = backwardation (event imminent).

    Steepening backwardation (spread rising) → event intensity building → ABSTAIN-from-buying signal;
    flattening → event passing. ``threshold`` is in IV (decimal) over the window.
    """
    y = _clean(front_minus_back_series)
    if y.size < 2:
        return None
    slope = _slope_per_step(y)
    total = float(y[-1] - y[0])
    backwardation = bool(y[-1] > 0)
    steepening = total > 0
    fired = abs(total) >= threshold
    return {
        "slope": slope,
        "change": total,
        "backwardation": backwardation,
        "steepening": bool(steepening),
        "fired": fired,
        "event_building": bool(backwardation and steepening and fired),
    }


@dataclass
class FlowMomentumRead:
    """Composite options-flow momentum read across the recorded chain series."""

    oi: dict | None = None
    gex: dict | None = None
    iv_rank: dict | None = None
    term: dict | None = None
    vol_direction: str = NEUTRAL     # SHORT_VOL | LONG_VOL | NEUTRAL (premium rich/cheap consensus)
    flip: bool = False               # dealer-gamma regime flip detected
    notes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "oi": self.oi, "gex": self.gex, "iv_rank": self.iv_rank, "term": self.term,
            "vol_direction": self.vol_direction, "flip": self.flip, "notes": self.notes,
        }


def flow_momentum(
    *,
    oi_series=None,
    gex_series=None,
    iv_rank_series=None,
    term_spread_series=None,
) -> FlowMomentumRead:
    """Fuse the recorded chain series into one flow-momentum read. Each component independently
    abstains when its series is missing/short — so a thin recorder history degrades gracefully."""
    oi = oi_velocity(oi_series) if oi_series is not None else None
    gex = gex_velocity(gex_series) if gex_series is not None else None
    ivr = iv_rank_velocity(iv_rank_series) if iv_rank_series is not None else None
    term = term_spread_velocity(term_spread_series) if term_spread_series is not None else None

    notes: list[str] = []
    # Consensus vol direction from IV-rank velocity + gamma flip (decorrelated reads of "rich vs cheap").
    vol_votes = []
    if ivr and ivr["fired"] and ivr["direction"] in (SHORT_VOL, LONG_VOL):
        vol_votes.append(ivr["direction"])
    if gex and gex["fired"] and gex["direction"] in (SHORT_VOL, LONG_VOL):
        vol_votes.append(gex["direction"])
    if vol_votes and all(v == vol_votes[0] for v in vol_votes):
        vol_direction = vol_votes[0]
    else:
        vol_direction = NEUTRAL
        if vol_votes:
            notes.append("vol_signals_conflict")
    flip = bool(gex and gex.get("flip"))
    if term and term.get("event_building"):
        notes.append("event_backwardation_building")
    return FlowMomentumRead(oi=oi, gex=gex, iv_rank=ivr, term=term,
                            vol_direction=vol_direction, flip=flip, notes=notes)


# Re-export directional tags so factors importing from here stay consistent.
__all__ = [
    "oi_velocity", "gex_velocity", "iv_rank_velocity", "term_spread_velocity",
    "flow_momentum", "FlowMomentumRead", "BULLISH", "BEARISH", "NEUTRAL", "LONG_VOL", "SHORT_VOL",
]
