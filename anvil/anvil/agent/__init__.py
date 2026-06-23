"""Grounded analyst — narrates the engine's numbers, never invents them.

Two layers: a deterministic narrator (always available; every number comes straight from the
engine) and an optional Claude-backed Q&A that is hard-grounded by a strict system prompt and a
compliance guardrail that blocks any actionable buy/sell/target/guarantee language before it
reaches the user. See docs/decisions/0004-calibration-first-compliance.md.
"""

from .analyst import GroundedAnalyst, build_context
from .guardrail import check_compliance, is_compliant

__all__ = ["GroundedAnalyst", "build_context", "check_compliance", "is_compliant"]
