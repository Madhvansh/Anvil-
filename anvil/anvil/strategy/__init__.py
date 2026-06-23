"""Anvil paper-trading strategy layer (PRIVATE to the paper-trading subsystem).

Converts the existing analytics into ranked, sized, defined/undefined-risk trade candidates with
a full decision policy. COMPLIANCE: this package emits directional buy/sell structures and must
never be wired into the public copilot/analyst/guardrail surface — it is reachable only behind the
``paper_trading`` feature flag.
"""

from __future__ import annotations

from .context import SignalContext
from .generate import GenConfig, generate_candidates
from .library import STRATEGIES, register
from .types import (
    ACTIONS,
    NO_TRADE,
    TRADE,
    Leg,
    TradeCandidate,
)

__all__ = [
    "SignalContext",
    "GenConfig",
    "generate_candidates",
    "STRATEGIES",
    "register",
    "TradeCandidate",
    "Leg",
    "ACTIONS",
    "TRADE",
    "NO_TRADE",
]
