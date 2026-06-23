"""Unusual options activity — surface strikes with abnormal flow.

Ranks strikes by volume/OI churn and OI change magnitude (vs a previous chain when available),
labels the buildup, and returns the most notable few. Reuses oi.classify_buildup/total_oi_change.
"""

from __future__ import annotations

from ..models import OptionChain
from .oi import classify_buildup, total_oi_change


def unusual_activity(chain: OptionChain, prev_chain: OptionChain | None = None, top: int = 8) -> dict:
    flags: list[dict] = []
    for row in chain.rows:
        oi_chg = row.oi_change
        if prev_chain is not None:
            prev = prev_chain.row(row.strike, row.option_type)
            if prev is not None:
                oi_chg = row.oi - prev.oi
        vol_oi = (row.volume / row.oi) if row.oi else 0.0
        # Combined "unusualness": fresh churn (volume relative to OI) + sizable OI swing.
        score = vol_oi + (abs(oi_chg) / (row.oi + 1.0))
        # price_change unknown intraday; buildup from OI swing sign on the strike's side.
        buildup = classify_buildup(0.0, oi_chg)
        flags.append(
            {
                "strike": row.strike,
                "option_type": row.option_type.value,
                "oi": row.oi,
                "oi_change": round(oi_chg, 1),
                "volume": row.volume,
                "vol_oi_ratio": round(vol_oi, 3),
                "buildup": buildup,
                "score": round(score, 4),
            }
        )

    flags.sort(key=lambda f: f["score"], reverse=True)
    notable = [f for f in flags if f["vol_oi_ratio"] > 0.5 or abs(f["oi_change"]) > 0][:top]

    return {
        "underlying": chain.underlying,
        "total_oi_change": total_oi_change(chain),
        "flags": notable,
        "note": "Volume-to-OI churn and OI swings; intraday buildup labels use the OI swing sign.",
    }
