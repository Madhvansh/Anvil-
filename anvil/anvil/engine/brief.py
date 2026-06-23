"""Daily brief — the first screen. Compresses the whole market read into ~5 plain lines:
current regime, market-implied expiry range, key OI walls, the biggest risk, what changed,
and the calibration/trust status. Composed from existing analytics; adds no new math.
"""

from __future__ import annotations


def _fmt(x: float | None) -> str:
    return f"{x:,.0f}" if isinstance(x, (int, float)) else "—"


def daily_brief(payload: dict, event: dict | None = None, calibration: dict | None = None, changed: dict | None = None) -> dict:
    u = payload.get("underlying", "?")
    spot = payload.get("spot")
    regime = (payload.get("regime") or {}).get("label")
    dist = payload.get("implied_distribution") or {}
    em = dist.get("expected_move_1sigma")
    oi = payload.get("oi") or {}
    gex = payload.get("gex") or {}

    rng = [round(spot - em, 1), round(spot + em, 1)] if (em and isinstance(spot, (int, float))) else None
    call_wall = (oi.get("call_resistance") or [[None]])[0][0]
    put_wall = (oi.get("put_support") or [[None]])[0][0]
    max_pain = oi.get("max_pain")
    flip = gex.get("zero_gamma_flip")

    risk_level = (event or {}).get("risk_level")
    cal_status = (calibration or {}).get("headline") or "Calibration sample still building."

    lines = []
    regime_h = (regime or "mixed").replace("_", " ")
    lines.append(f"{u} is in a {regime_h} regime." + (f" Spot {_fmt(spot)}." if spot else ""))
    if rng:
        lines.append(f"Market-implied expiry range: {_fmt(rng[0])}–{_fmt(rng[1])} (±1σ).")
    if call_wall or put_wall:
        lines.append(f"Largest call wall: {_fmt(call_wall)}. Largest put wall: {_fmt(put_wall)}.")
    if risk_level:
        lines.append(f"Expiry/event risk: {risk_level.upper()}." + (f" Max pain {_fmt(max_pain)}." if max_pain else ""))
    if changed and changed.get("available") and changed.get("narrative"):
        lines.append(changed["narrative"])
    lines.append(cal_status)

    return {
        "underlying": u,
        "spot": spot,
        "regime": regime,
        "expected_range": rng,
        "key_levels": {
            "call_wall": call_wall,
            "put_wall": put_wall,
            "max_pain": max_pain,
            "zero_gamma_flip": flip,
        },
        "risk_level": risk_level,
        "calibration_status": cal_status,
        "what_changed": changed.get("narrative") if (changed and changed.get("available")) else None,
        "lines": lines,
        "provenance": payload.get("provenance"),
    }
