"""Alert evaluation — turn rules + current analytics into natural-language, grounded alerts.

Alerts read like a human wrote them ("NIFTY moved below the zero-gamma flip; volatility risk
increased."), carry a traffic-light severity, and attach the triggering numbers + provenance.
Pure function over the analyze payload (+ optional prior payload and precomputed extras).
"""

from __future__ import annotations

import math


def _sign(x: float) -> int:
    return (x > 0) - (x < 0)


def _event(rule: dict, severity: str, title: str, body: str, detail: dict) -> dict:
    return {
        "rule_id": rule.get("id"),
        "kind": rule.get("kind"),
        "underlying": rule.get("underlying"),
        "severity": severity,
        "title": title,
        "body": body,
        "detail": detail,
    }


def evaluate_rule(
    rule: dict, payload: dict, prev: dict | None = None, extras: dict | None = None
) -> dict | None:
    """Return an alert event dict if the rule fires now, else None."""
    kind = rule.get("kind")
    params = rule.get("params") or {}
    extras = extras or {}
    u = payload.get("underlying", rule.get("underlying", "?"))
    spot = payload.get("spot")
    gex = payload.get("gex") or {}
    oi = payload.get("oi") or {}

    if kind == "price_band":
        lo, hi = params.get("lower"), params.get("upper")
        if spot is None or lo is None or hi is None:
            return None
        if spot < lo:
            return _event(rule, "warn", f"{u} broke below {lo:,.0f}", f"Spot {spot:,.0f} is under your lower band {lo:,.0f}.", {"spot": spot, "lower": lo})
        if spot > hi:
            return _event(rule, "warn", f"{u} broke above {hi:,.0f}", f"Spot {spot:,.0f} is over your upper band {hi:,.0f}.", {"spot": spot, "upper": hi})
        return None

    if kind == "pcr_threshold":
        pcr = oi.get("pcr_oi")
        op, val = params.get("op", ">"), params.get("value")
        if pcr is None or val is None:
            return None
        ops = {">": pcr > val, ">=": pcr >= val, "<": pcr < val, "<=": pcr <= val}
        hit = ops.get(op, pcr > val)
        if hit:
            return _event(rule, "info", f"{u} PCR(OI) {op} {val}", f"Put/Call OI ratio is {pcr:.2f} ({op} {val}).", {"pcr_oi": pcr, "op": op, "value": val})
        return None

    if kind == "gex_flip_cross":
        flip = gex.get("zero_gamma_flip")
        if flip is None or spot is None or not prev:
            return None
        pflip = (prev.get("gex") or {}).get("zero_gamma_flip")
        pspot = prev.get("spot")
        if pflip is None or pspot is None:
            return None
        if _sign(spot - flip) != _sign(pspot - pflip):
            below = spot < flip
            sev = "critical" if below else "info"
            title = (f"{u} moved below the zero-gamma flip" if below else f"{u} moved back above the zero-gamma flip")
            body = ("Dealers likely short gamma now — volatility risk increased; moves may amplify." if below
                    else "Dealers likely long gamma again — moves may be dampened/pinned.")
            return _event(rule, sev, title, body, {"spot": spot, "zero_gamma_flip": flip})
        return None

    if kind == "oi_wall_break":
        call_wall = (oi.get("call_resistance") or [[None]])[0][0]
        put_wall = (oi.get("put_support") or [[None]])[0][0]
        if spot is None:
            return None
        if call_wall is not None and spot > call_wall:
            return _event(rule, "warn", f"{u} broke its call wall {call_wall:,.0f}", f"Spot {spot:,.0f} cleared the largest call-OI strike — resistance gave way.", {"spot": spot, "call_wall": call_wall})
        if put_wall is not None and spot < put_wall:
            return _event(rule, "warn", f"{u} broke its put wall {put_wall:,.0f}", f"Spot {spot:,.0f} fell through the largest put-OI strike — support gave way.", {"spot": spot, "put_wall": put_wall})
        return None

    if kind == "iv_crush":
        crush = extras.get("iv_crush") or {}
        score = crush.get("crush_score")
        thresh = params.get("min_score", 66)
        if score is not None and score >= thresh:
            return _event(rule, "warn", f"{u} IV-crush risk high ({score:.0f})", crush.get("warning", ""), {"crush_score": score})
        return None

    if kind == "event_risk":
        ev = extras.get("event_risk") or {}
        level = ev.get("risk_level")
        want = params.get("level", "high")
        order = {"low": 0, "medium": 1, "high": 2}
        if level and order.get(level, 0) >= order.get(want, 2):
            burn = ev.get("theta_burn_pct")
            burn_s = f"{burn:.1%}" if isinstance(burn, (int, float)) else "n/a"
            return _event(rule, "warn" if level == "high" else "info", f"{u} expiry/event risk: {level.upper()}", f"Days to expiry {ev.get('days_to_expiry')}, theta burn {burn_s}.", ev)
        return None

    if kind == "unusual_activity":
        ua = extras.get("unusual") or {}
        flags = ua.get("flags") or []
        if len(flags) >= params.get("min_flags", 3):
            return _event(rule, "info", f"{u}: unusual options activity ({len(flags)} strikes)", "Several strikes show abnormal volume/OI churn.", {"flag_count": len(flags)})
        return None

    return None


def evaluate_rules(rules: list[dict], payload: dict, prev: dict | None = None, extras: dict | None = None) -> list[dict]:
    out = []
    for rule in rules:
        if not rule.get("enabled", True):
            continue
        ev = evaluate_rule(rule, payload, prev=prev, extras=extras)
        if ev is not None and not (isinstance(ev.get("detail"), dict) and any(
            isinstance(v, float) and math.isnan(v) for v in ev["detail"].values()
        )):
            out.append(ev)
    return out
