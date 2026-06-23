"""Chain sources — where each tick's OptionChain comes from.

``LiveChainSource`` wraps the live connector (``get_connector`` + parity forward). ``ReplaySource``
reproduces a deterministic intraday path: a seeded GBM spot walk that rebuilds the demo chain (or,
when present, reads recorded snapshots) at each timestamp — fully reproducible with zero keys, so a
closed-market mock session reproduces bit-for-bit. Both expose ``chain(underlying, ts)``.
"""

from __future__ import annotations

import numpy as np

from ..config import SETTINGS
from ..ingest import get_connector
from ..ingest.base import attach_parity_forward
from ..ingest.demo import build_demo_chain
from ..models import OptionChain

_DEFAULT_BASE_SPOT = {"NIFTY": 24000.0, "BANKNIFTY": 52000.0, "FINNIFTY": 23500.0, "SENSEX": 79000.0}
_YEAR_SECONDS = 365.0 * 24 * 3600
_DEMO_ATM_IV = 0.13  # build_demo_chain's default ATM IV


class LiveChainSource:
    """Pull a fresh chain per tick from the configured connector (REST; WS feed lands in Phase 3b)."""

    def __init__(self, source: str | None = None):
        self.source = source
        self._conn = get_connector(source)

    def chain(self, underlying: str, ts: str | None = None) -> OptionChain:
        return attach_parity_forward(self._conn.get_chain(underlying))


class ReplaySource:
    """Deterministic synthetic replay: a seeded spot path -> demo chains, fixed expiry.

    The per-step realized vol is calibrated to the chain's IMPLIED vol times the variance risk
    premium (``realized ≈ vrp_ratio × implied``) — the same assumption the strategies trade on —
    so the synthetic path doesn't secretly run hotter than what sellers priced. ``step_vol`` can be
    overridden to stress-test a higher-realized-vol regime.
    """

    def __init__(self, underlyings, start_ts: str, expiry: str, steps: int, seed: int = 7,
                 cadence_s: int = 3600, base_iv: float = _DEMO_ATM_IV, step_vol: float | None = None):
        self.underlyings = [u.upper() for u in underlyings]
        self.start_ts = start_ts
        self.expiry = expiry
        self.steps = int(steps)
        if step_vol is not None:
            self.step_vol = float(step_vol)
        else:
            dt = max(float(cadence_s), 1.0) / _YEAR_SECONDS
            self.step_vol = float(base_iv) * float(SETTINGS.paper_vrp_ratio) * float(np.sqrt(dt))
        rng = np.random.default_rng(int(seed))
        # Pre-generate one independent multiplicative path per underlying (deterministic).
        self._paths: dict[str, np.ndarray] = {}
        for u in self.underlyings:
            shocks = rng.normal(0.0, self.step_vol, size=self.steps)
            self._paths[u] = float(_DEFAULT_BASE_SPOT.get(u, 24000.0)) * np.exp(np.cumsum(shocks))

    def spot_at(self, underlying: str, step: int) -> float:
        path = self._paths[underlying.upper()]
        return float(path[min(step, len(path) - 1)])

    def chain(self, underlying: str, ts: str, step: int = 0) -> OptionChain:
        return build_demo_chain(underlying.upper(), spot=self.spot_at(underlying, step), expiry=self.expiry, timestamp=ts)
