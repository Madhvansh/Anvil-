"""Real-day chain source — replay the REAL trading day.

Snapshots the real current chain once (the **real IV smile + OI + lot + expiry + forward**), then
walks today's **real intraday underlying path** (broker historical candles) and reprices the chain at
each timestamp via Black-76 off the held smile — the same recipe as ``ingest.demo.build_demo_chain``,
with the parametric smile swapped for the real captured one.

This makes the *smile-stability* assumption explicit: IV(strike) is frozen at the snapshot; only the
underlying and time-to-expiry move across the day. It is NOT a true backtest (no historical option
quotes) — it's "what the strategy would have done given the real path under a frozen smile". The
forward is tagged ``realday_smile_held`` so provenance never lies. One source per underlying; exposes
``chain(ts, step)`` (mirrors ``ReplaySource.chain``).
"""

from __future__ import annotations

import numpy as np
from scipy.interpolate import interp1d

from ..config import lot_size
from ..engine import greeks as gk
from ..engine.util import year_fraction
from ..ingest.base import attach_parity_forward
from ..models import ChainRow, OptionChain, OptionType

_RFR = 0.065  # risk-free rate used for Black-76 (matches build_demo_chain)


class RealDaySource:
    def __init__(self, underlying: str, conn, *, interval_min: int = 15, candles=None):
        self.underlying = underlying.upper()
        self.conn = conn
        self.anchor_chain = attach_parity_forward(conn.get_chain(self.underlying))
        a = self.anchor_chain
        self.expiry = a.expiry
        self.anchor_spot = float(a.spot or 0.0)
        self.anchor_forward = float(a.future_price or a.spot or 0.0)
        self.lot = a.lot_size or lot_size(self.underlying)
        self.vix = a.vix
        # Hold the real per-strike smile + OI from the snapshot.
        self._strikes = sorted({r.strike for r in a.rows})
        self._oi: dict[tuple[float, OptionType], tuple[float, float, float]] = {}
        ks_c, ivs_c, ks_p, ivs_p = [], [], [], []
        for r in a.rows:
            self._oi[(r.strike, r.option_type)] = (r.oi, r.oi_change, r.volume)
            if r.iv and r.iv > 0:
                if r.option_type == OptionType.CALL:
                    ks_c.append(r.strike)
                    ivs_c.append(r.iv)
                else:
                    ks_p.append(r.strike)
                    ivs_p.append(r.iv)
        self._smile_c = self._mk_smile(ks_c, ivs_c)
        self._smile_p = self._mk_smile(ks_p, ivs_p) or self._smile_c
        if self._smile_c is None:
            self._smile_c = self._smile_p
        # Real intraday underlying path (nearest-first): [(iso_ts, o, h, l, c), ...].
        self.candles = candles if candles is not None else conn.get_historical_candles(
            self.underlying, interval_min=interval_min
        )
        if not self.candles:
            raise RuntimeError(f"No intraday candles for {self.underlying} — cannot replay the real day.")

    @staticmethod
    def _mk_smile(ks, ivs):
        if not ks:
            return None
        if len(ks) == 1:
            v = float(ivs[0])
            return lambda k: v
        order = np.argsort(ks)
        ksa, ivsa = np.array(ks)[order], np.array(ivs)[order]
        f = interp1d(ksa, ivsa, kind="linear", bounds_error=False, fill_value=(float(ivsa[0]), float(ivsa[-1])))
        return lambda k: float(np.clip(f(k), 1e-3, 5.0))

    def timestamps(self) -> list[str]:
        return [c[0] for c in self.candles]

    def day_open(self) -> float:
        return float(self.candles[0][1])

    def spot_at(self, step: int) -> float:
        return float(self.candles[min(step, len(self.candles) - 1)][4])  # candle close

    def chain(self, ts: str, step: int = 0) -> OptionChain:
        spot = self.spot_at(step)
        # Preserve the snapshot's (parity-derived) basis by scaling the forward with spot.
        forward = self.anchor_forward * (spot / self.anchor_spot) if self.anchor_spot else spot
        T = max(year_fraction(self.expiry, ts), 1e-6)
        rows: list[ChainRow] = []
        for k in self._strikes:
            for ot, smile in ((OptionType.CALL, self._smile_c), (OptionType.PUT, self._smile_p)):
                iv = smile(k) if smile else 0.13
                price = max(float(gk.price(ot, forward, float(k), T, _RFR, iv)), 0.05)
                oi, oic, vol = self._oi.get((k, ot), (0.0, 0.0, 0.0))
                rows.append(
                    ChainRow(
                        strike=float(k), option_type=ot, ltp=round(price, 2),
                        bid=round(price * 0.995, 2), ask=round(price * 1.005, 2),
                        oi=oi, oi_change=oic, volume=vol, iv=round(float(iv), 4),
                    )
                )
        return OptionChain(
            underlying=self.underlying, spot=spot, expiry=self.expiry, timestamp=ts, rows=rows,
            future_price=round(forward, 2), future_price_source="realday_smile_held",
            vix=self.vix, lot_size=self.lot, underlying_prev_close=round(self.anchor_spot, 2),
        )
