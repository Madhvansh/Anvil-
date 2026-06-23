"""Grounded analyst: a deterministic narrator (always on) + an optional Claude Q&A.

The narrator composes prose purely from engine numbers — it cannot hallucinate a price call.
The optional `ask()` path calls Claude with a strict, grounded system prompt and runs every
response through the compliance guardrail before returning it.
"""

from __future__ import annotations

import os

from .guardrail import check_compliance

DISCLAIMER = "Analytics & education only — not investment advice. Probabilities are market-implied (risk-neutral)."

SYSTEM_PROMPT = """You are Anvil's options analyst for Indian index options. STRICT RULES:
- Use ONLY the numbers in the provided CONTEXT JSON. Never invent or estimate a price, level, or probability that is not in the context.
- You may explain dealer positioning (GEX/zero-gamma flip), the market-implied distribution, OI, and the user's beta-weighted risk, and what they imply about *regime* (mean-reverting vs trend-amplifying) and *probabilities*.
- NEVER give an actionable recommendation: no buy/sell/short, no price targets, no stop-losses, no "you should", no guarantees, no accuracy/return claims.
- Frame everything as probabilities, ranges, and scenarios. End with the disclaimer.
- If asked for a trade call or a price prediction, decline and reframe as probabilities/scenarios.
"""


def build_context(payload: dict, ledger_metrics: dict | None = None) -> dict:
    """A compact, grounded context pack for the agent (only engine-derived numbers)."""
    ctx = {
        "underlying": payload.get("underlying"),
        "spot": payload.get("spot"),
        "expiry": payload.get("expiry"),
        "regime": payload.get("regime"),
        "gex": payload.get("gex"),
        "implied_distribution": payload.get("implied_distribution"),
        "oi": payload.get("oi"),
        "skew": payload.get("skew"),
        "portfolio": payload.get("portfolio"),
    }
    if ledger_metrics:
        ctx["calibration"] = {
            "resolved_count": ledger_metrics.get("resolved_count"),
            "brier": ledger_metrics.get("brier"),
            "ece": ledger_metrics.get("ece"),
            "band_coverage": ledger_metrics.get("band_coverage"),
        }
    return ctx


def narrate(payload: dict, mode: str = "trader") -> str:
    """Deterministic, always-safe narration built straight from engine numbers.

    ``mode`` controls disclosure depth (same engine, different detail):
      simple  — plain-language regime + expected range only;
      trader  — adds GEX flip, max pain / PCR, and the beta-weighted book;
      expert  — adds the full regime drivers.
    """
    u = payload.get("underlying", "?")
    spot = payload.get("spot")
    regime = payload.get("regime", {}) or {}
    gex = payload.get("gex", {}) or {}
    dist = payload.get("implied_distribution") or {}
    oi = payload.get("oi", {}) or {}
    lines = [f"**{u} — regime read** (spot {spot:,.0f})" if isinstance(spot, (int, float)) else f"**{u} — regime read**"]
    if regime.get("label"):
        lines.append(f"- Regime: **{regime['label'].replace('_', ' ')}**")
    if mode == "expert":
        for d in regime.get("drivers", []):
            lines.append(f"  - {d}")
    if dist:
        em = dist.get("expected_move_1sigma")
        if em is not None and isinstance(spot, (int, float)):
            lines.append(f"- Market-implied ±1σ move ≈ {em:,.0f} pts → roughly [{spot - em:,.0f}, {spot + em:,.0f}] by expiry.")
    if mode != "simple":
        if gex.get("zero_gamma_flip") is not None:
            lines.append(f"- Zero-gamma flip ≈ {gex['zero_gamma_flip']:,.0f}; total GEX {gex.get('total_gex', 0):,.0f}.")
        if oi.get("max_pain") is not None:
            lines.append(f"- Max pain {oi['max_pain']:,.0f}; PCR(OI) {oi.get('pcr_oi'):.2f}." if oi.get("pcr_oi") else f"- Max pain {oi['max_pain']:,.0f}.")
        if payload.get("portfolio"):
            pf = payload["portfolio"]
            lines.append(f"- Your book (beta-weighted to {pf['benchmark']}): net δ {pf['net_delta']:,.0f}, "
                         f"γ {pf['net_gamma']:.3f}, θ/day {pf['net_theta']:,.0f}, vega/1% {pf['net_vega']:,.0f}.")
    lines.append("")
    lines.append(f"_{DISCLAIMER}_")
    return "\n".join(lines)


class GroundedAnalyst:
    def __init__(self, model: str | None = None):
        # Default to the latest, most capable Claude model; override via ANVIL_AGENT_MODEL.
        self.model = model or os.environ.get("ANVIL_AGENT_MODEL", "claude-opus-4-8")

    def narrate(self, payload: dict, mode: str = "trader") -> str:
        return narrate(payload, mode)

    def ask(self, question: str, payload: dict, ledger_metrics: dict | None = None) -> dict:
        """Answer a question grounded in the engine numbers. Uses Claude if ANTHROPIC_API_KEY is
        set (output is guardrailed); otherwise returns the deterministic narration."""
        import json

        if not os.environ.get("ANTHROPIC_API_KEY"):
            return {"answer": self.narrate(payload), "grounded": True, "model": "deterministic-narrator",
                    "violations": [], "note": "Set ANTHROPIC_API_KEY for conversational Q&A."}
        try:
            import anthropic
        except ImportError:
            return {"answer": self.narrate(payload), "grounded": True, "model": "deterministic-narrator",
                    "violations": [], "note": "anthropic SDK not installed (`pip install anthropic`)."}

        ctx = build_context(payload, ledger_metrics)
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model=self.model,
            max_tokens=700,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"CONTEXT:\n{json.dumps(ctx, default=str)}\n\nQUESTION: {question}"}],
        )
        text = "".join(block.text for block in msg.content if getattr(block, "type", None) == "text")
        violations = check_compliance(text)
        if violations:
            # Refuse to surface non-compliant output; fall back to the safe narration.
            return {"answer": self.narrate(payload), "grounded": True, "model": self.model,
                    "violations": violations, "note": "LLM output blocked by compliance guardrail; showing grounded summary."}
        return {"answer": text, "grounded": True, "model": self.model, "violations": []}
