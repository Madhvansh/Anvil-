"""Factor interface + registry + runner.

A ``FactorSignal`` is a small, explainable verdict: did the factor fire, how strongly (0..1), in
what direction, at what honest edge tier, and is it allowed in the current regime (``regime_mask``).
``compute_factors`` runs every registered factor with a per-factor guard so one bad factor never
sinks the pass (mirrors ``strategy.generate``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

# Honest edge tiers. STRONG factors may, with measured backing, drive a headline tip; CONFIRMATION
# factors never headline alone — they only corroborate (PCR, raw drift, etc.).
STRONG = "strong"
CONFIRMATION = "confirmation"


@dataclass
class FactorSignal:
    name: str
    fired: bool
    strength: float  # 0..1 (not a probability — a relative conviction weight)
    direction: str  # "" or a strategy.types direction tag (bullish/bearish/neutral/long_vol/short_vol)
    edge_tier: str  # STRONG | CONFIRMATION
    drivers: dict = field(default_factory=dict)
    regime_mask: bool = True  # True = allowed in the current regime; the gate sets False to suppress

    @property
    def active(self) -> bool:
        """Fired AND allowed in the current regime — the only signals that count toward a tip."""
        return bool(self.fired and self.regime_mask)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "fired": self.fired,
            "active": self.active,
            "strength": self.strength,
            "direction": self.direction,
            "edge_tier": self.edge_tier,
            "regime_mask": self.regime_mask,
            "drivers": self.drivers,
        }


Factor = Callable[[object], "FactorSignal | None"]
FACTORS: dict[str, Factor] = {}


def register(name: str):
    def deco(fn: Factor) -> Factor:
        FACTORS[name] = fn
        return fn

    return deco


def compute_factors(ctx) -> list[FactorSignal]:
    """Run every registered factor over ``ctx``; skip (don't crash on) any that error."""
    out: list[FactorSignal] = []
    for fn in FACTORS.values():
        try:
            sig = fn(ctx)
        except Exception:  # noqa: BLE001 - one factor erroring must not sink the pass
            continue
        if sig is not None:
            out.append(sig)
    return out


def fired_names(signals: list[FactorSignal]) -> list[str]:
    """Names of signals that fired AND survived the regime mask — the tip's signals_fired."""
    return [s.name for s in signals if s.active]
