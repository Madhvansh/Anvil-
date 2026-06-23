"""Factor library — composable, regime-gated alpha factors over the existing ``SignalContext``.

Each factor is a pure ``(ctx) -> FactorSignal`` registered via ``@register(name)`` (mirrors
``strategy.library``). Factors READ the engine analytics already computed on the context (GEX,
implied distribution, regime, IV rank, OI walls, event/crush) — no new pricing. They are tagged with
an honest edge tier (STRONG vs CONFIRMATION-only) reflecting the empirical evidence, and the regime
gate masks factors that don't belong in the current regime. Their fired/active names feed a tip's
``signals_fired`` and weight its conviction.
"""

from . import chain_analytics  # noqa: F401 - registers the chain-dynamics factors (skew slope, OI thrust, blocks, 0DTE)
from . import dealer_flow  # noqa: F401 - registers the vanna/charm + gamma-flip-S/R dealer-flow factors
from . import events  # noqa: F401 - registers the scheduled-event gate factor
from . import index_options  # noqa: F401 - registers the v1 factors as a side-effect
from . import momentum  # noqa: F401 - registers the multi-timeframe + flow momentum factors
from .base import (
    CONFIRMATION,
    FACTORS,
    STRONG,
    FactorSignal,
    compute_factors,
    fired_names,
    register,
)
from .regime_gate import (
    EVENT_CRUSH,
    NEUTRAL_REGIME,
    PIN_LOW_VOL,
    TREND_HIGH_VOL,
    apply_regime_mask,
    classify_regime,
)

__all__ = [
    "FactorSignal",
    "compute_factors",
    "fired_names",
    "register",
    "FACTORS",
    "STRONG",
    "CONFIRMATION",
    "classify_regime",
    "apply_regime_mask",
    "PIN_LOW_VOL",
    "TREND_HIGH_VOL",
    "EVENT_CRUSH",
    "NEUTRAL_REGIME",
]
