"""
Empirical recalibration — make stated confidence TRUTHFUL.

The raw model emits a directional lean and a capped probability. History (backtest, and
later the live resolved track record) tells us what that probability is ACTUALLY worth.
This module fits a simple monotone map  stated_confidence -> realized_hit_rate  from the
most recent reliability curve and applies it, so the number we show is honest.

Right now that map is roughly flat at ~0.50 (the backtest found no directional edge after
costs), so calibrated confidence collapses toward a coin flip and almost everything is
marked WATCH / not edge-verified. That is the honest, intended behaviour: we would rather
say "no proven edge, abstain" than print a confident number we cannot stand behind.

When real edge later appears (richer features / ML meta-layer / longer holds), the same map
will lift calibrated confidence and flip tips to ACTIONABLE — but only once MEASURED.
"""
from __future__ import annotations

import glob
import json
import os

import config

# A tip is only ACTIONABLE if calibrated confidence clears this AND edge is verified.
ACT_THRESHOLD = 0.55
# Edge is "verified" only if some bucket's actual hit-rate beats this with a real sample.
EDGE_HITRATE_BAR = 0.53
EDGE_MIN_SAMPLE = 200


def _latest_backtest() -> dict | None:
    files = sorted(glob.glob(os.path.join(config.REPORTS_DIR, "backtest_*.json")))
    if not files:
        return None
    try:
        return json.load(open(files[-1]))
    except Exception:
        return None


def _reliability_points() -> list[tuple[float, float, int]]:
    """(stated, actual, n) points from the latest backtest's full-history curve."""
    bt = _latest_backtest()
    if not bt:
        return []
    curve = (bt.get("overall") or {}).get("reliability_curve") or []
    return [(c["stated"], c["actual"], c["n"]) for c in curve if "stated" in c and "actual" in c]


def fit():
    """Return (slope, intercept, edge_verified). Linear LS stated->actual, sample-weighted."""
    pts = _reliability_points()
    if not pts:
        return None  # no history → identity (raw shown, flagged unverified)
    sw = sum(n for _, _, n in pts)
    mx = sum(s * n for s, _, n in pts) / sw
    my = sum(a * n for _, a, n in pts) / sw
    num = sum(n * (s - mx) * (a - my) for s, a, n in pts)
    den = sum(n * (s - mx) ** 2 for s, _, n in pts)
    slope = num / den if den > 1e-12 else 0.0
    intercept = my - slope * mx
    edge_verified = any(a >= EDGE_HITRATE_BAR and n >= EDGE_MIN_SAMPLE for _, a, n in pts)
    return slope, intercept, edge_verified, my


def assess(raw_conf: float) -> dict:
    """Map a raw confidence to an honest one + an ACTIONABLE/WATCH status."""
    f = fit()
    if f is None:
        # no track record yet: don't claim calibration; show raw but mark unverified
        return {"calibrated_confidence": round(raw_conf, 3), "edge_verified": False,
                "status": "WATCH", "basis": "no_history_identity"}
    slope, intercept, edge_verified, mean_actual = f
    cal = slope * raw_conf + intercept
    # guard against tiny samples producing silly slopes: keep within [mean_actual±0.1] and [0,1]
    cal = max(0.0, min(1.0, cal))
    status = "ACTIONABLE" if (edge_verified and cal >= ACT_THRESHOLD) else "WATCH"
    return {"calibrated_confidence": round(cal, 3), "edge_verified": bool(edge_verified),
            "status": status, "basis": "backtest_reliability"}


def headline() -> dict:
    """One-line honest status for reports/UI."""
    f = fit()
    if f is None:
        return {"edge_verified": False, "message": "No track record yet — predictions are unproven analytics."}
    _, _, edge_verified, mean_actual = f
    return {
        "edge_verified": bool(edge_verified),
        "measured_hit_rate": round(mean_actual, 3),
        "message": (
            f"No directional edge proven yet — backtested hit-rate ~{mean_actual:.0%} (<= coin flip "
            "after costs). Tips are analytics/context, NOT validated signals. Default stance: abstain."
            if not edge_verified else
            f"Edge measured: hit-rate ~{mean_actual:.0%}. Still probabilistic; not advice."
        ),
    }
