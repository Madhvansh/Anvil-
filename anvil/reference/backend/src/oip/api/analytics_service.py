"""Read services for the analytics + calibration endpoints.

Analytics are computed live from the data source's chain (deterministic on the offline fixture),
on the Black-76 futures engine. Every payload carries the disclaimer; risk‑neutral / unvalidated
fields are flagged honestly.
"""

from __future__ import annotations

from ..analytics import oi as oi_mod
from ..analytics import vol as vol_mod
from ..analytics.gex import compute_gex
from ..analytics.implied_dist import implied_distribution
from ..calibration.ledger import CalibrationLedger
from ..constants import DISCLAIMER
from ..data.source import ChainRequest, DataSource


def get_analytics_view(underlying: str, *, source: DataSource) -> dict:
    chain = source.fetch_chain(ChainRequest(underlying=underlying.upper()))
    gex = compute_gex(chain)
    dist = implied_distribution(chain)
    walls = oi_mod.oi_walls(chain)
    return {
        "underlying": chain.underlying,
        "spot": chain.spot,
        "future_price": chain.future_price,
        "future_price_source": chain.future_price_source.value,
        "expiry": chain.rows[0].expiry.isoformat() if chain.rows else None,
        "snapshot_ts": chain.snapshot_ts.isoformat(),
        "oi": {
            "pcr_oi": oi_mod.pcr_oi(chain),
            "pcr_volume": oi_mod.pcr_volume(chain),
            "max_pain": oi_mod.max_pain(chain),
            "call_resistance": walls.call_resistance,
            "put_support": walls.put_support,
        },
        "vol": {
            "atm_iv": vol_mod.atm_iv(chain),
            "skew": vol_mod.skew(chain),
            "smile": vol_mod.iv_smile(chain),
        },
        "gex": {
            "total_gex": gex.total_gex,
            "zero_gamma_flip": gex.zero_gamma_flip,
            "call_walls": gex.call_walls,
            "put_walls": gex.put_walls,
            "needs_nse_validation": gex.needs_nse_validation,
        },
        "implied_distribution": {
            "atm_iv": dist.atm_iv,
            "em_atm_iv": dist.em_atm_iv,
            "em_straddle": dist.em_straddle,
            "prob_above_future": dist.prob_above(chain.future_price),
            "needs_real_world_calibration": dist.needs_real_world_calibration,
        },
        "disclaimer": DISCLAIMER,
    }


def get_calibration_summary(underlying: str | None, *, ledger: CalibrationLedger) -> dict:
    summary = ledger.summary(underlying)
    summary["disclaimer"] = DISCLAIMER
    summary["note"] = (
        "Calibration is computed on realized outcomes of logged forecasts. Empty until forecasts "
        "have been logged and resolved; a reliability curve is only meaningful with a track record."
    )
    return summary
