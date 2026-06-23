"""\"What changed since yesterday\" — a field-level diff between two analyze payloads.

Daily delta is what brings users back: OI walls shifting, IV expanding/compressing, the GEX
flip moving, the expected range widening, the regime flipping. Pure function over two payloads.
"""

from __future__ import annotations

_FIELDS = [
    ("spot", lambda p: p.get("spot")),
    ("total_gex", lambda p: (p.get("gex") or {}).get("total_gex")),
    ("zero_gamma_flip", lambda p: (p.get("gex") or {}).get("zero_gamma_flip")),
    ("atm_iv", lambda p: (p.get("implied_distribution") or {}).get("atm_iv")),
    ("expected_move_1sigma", lambda p: (p.get("implied_distribution") or {}).get("expected_move_1sigma")),
    ("pcr_oi", lambda p: (p.get("oi") or {}).get("pcr_oi")),
    ("max_pain", lambda p: (p.get("oi") or {}).get("max_pain")),
    ("regime", lambda p: (p.get("regime") or {}).get("label")),
]


def _narrative(changes: list[dict]) -> str:
    bits: list[str] = []
    by = {c["field"]: c for c in changes}
    if "regime" in by:
        bits.append(f"regime flipped to {str(by['regime']['to']).replace('_', ' ')}")
    if "atm_iv" in by:
        bits.append("IV expanded" if by["atm_iv"]["direction"] == "up" else "IV compressed")
    if "expected_move_1sigma" in by:
        bits.append("expected range widened" if by["expected_move_1sigma"]["direction"] == "up" else "expected range narrowed")
    if "zero_gamma_flip" in by:
        bits.append(f"zero-gamma flip moved {by['zero_gamma_flip']['direction']}")
    if "max_pain" in by:
        bits.append(f"max pain moved {by['max_pain']['direction']}")
    if not bits:
        return "Little changed versus the prior snapshot."
    return "Since the prior snapshot: " + ", ".join(bits) + "."


def what_changed(today: dict, baseline: dict | None) -> dict:
    if not baseline:
        return {"available": False, "note": "No prior snapshot yet — this is the first observation."}
    changes: list[dict] = []
    for name, getter in _FIELDS:
        a, b = getter(baseline), getter(today)
        if a is None or b is None:
            continue
        if name == "regime":
            if a != b:
                changes.append({"field": name, "from": a, "to": b, "direction": "changed"})
            continue
        if a == b:
            continue
        delta = b - a
        changes.append(
            {
                "field": name,
                "from": round(a, 4),
                "to": round(b, 4),
                "delta": round(delta, 4),
                "pct": round(delta / a, 4) if a else None,
                "direction": "up" if delta > 0 else "down",
            }
        )
    return {
        "available": True,
        "as_of_today": today.get("timestamp"),
        "as_of_baseline": baseline.get("timestamp"),
        "changes": changes,
        "narrative": _narrative(changes),
    }
