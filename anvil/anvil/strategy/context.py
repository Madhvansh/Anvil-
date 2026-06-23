"""SignalContext — compute the analytics surface ONCE and expose typed accessors to strategies.

This is the single seam between the rich (existing) engine and the (new) strategy library. It
reuses every engine module READ-ONLY — no new analytics, no new pricing — and adds only the
chain-navigation helpers (nearest strike, mids, per-leg liquidity/spread) strategies need to
build real structures off real chain rows.
"""

from __future__ import annotations

from ..config import SETTINGS
from ..engine import oi as oi_mod
from ..engine.dealer_flow import DealerFlowResult, compute_dealer_flow
from ..engine.event_risk import event_risk
from ..engine.flow_momentum import FlowMomentumRead, flow_momentum
from ..engine.forward import resolve_forward
from ..engine.gex import GEXResult, compute_gex
from ..engine.implied_dist import ImpliedDistribution, implied_distribution
from ..engine.iv_crush import iv_crush_warning
from ..engine.momentum import MomentumRead, multi_timeframe_momentum
from ..engine.regime import RegimeRead, read_regime
from ..engine.unusual import unusual_activity
from ..engine.util import year_fraction
from ..engine.vol import iv_rank, skew
from ..models import ChainRow, OptionChain, OptionType, Position

# Recognized keys for the optional flow-series block (recorded chain time-series → flow momentum).
_FLOW_SERIES_KEYS = {"oi_series", "gex_series", "iv_rank_series", "term_spread_series"}


class SignalContext:
    """Bundles a chain + its analytics. Built once per underlying per tick."""

    def __init__(
        self,
        chain: OptionChain,
        positions: list[Position] | None = None,
        iv_history: list[float] | None = None,
        prev_chain: OptionChain | None = None,
        source: str | None = None,
        *,
        closes: list[float] | None = None,
        bars_by_tf: dict[str, list[float]] | None = None,
        flow_series: dict[str, list[float]] | None = None,
        intraday_session: dict | None = None,
    ):
        self.chain = chain
        self.positions = positions or []
        self.iv_history = iv_history or []
        self.source = source
        self.underlying = chain.underlying
        self.spot = float(chain.spot)
        self.expiry = chain.expiry
        self.timestamp = chain.timestamp
        self.r = SETTINGS.risk_free_rate
        self.T = max(year_fraction(chain.expiry, chain.timestamp), 1e-6)
        self.forward, self.forward_source = resolve_forward(chain)

        # Engine reads (computed once).
        self.gex: GEXResult = compute_gex(chain)
        # Dealer-flow hedging stack (vanna/charm exposure + gamma-flip S/R) — reuses the GEX above.
        # Overlay only: a failure must never sink context construction (degrade to None → factors abstain).
        try:
            self.dealer_flow: DealerFlowResult | None = compute_dealer_flow(chain, gex_result=self.gex)
        except Exception:  # noqa: BLE001
            self.dealer_flow = None
        self.dist: ImpliedDistribution | None = implied_distribution(chain)
        self.regime: RegimeRead = read_regime(chain, gex=self.gex, dist=self.dist)
        self.walls = oi_mod.oi_walls(chain, n=3)
        self.max_pain = oi_mod.max_pain(chain)
        self.pcr_oi = oi_mod.pcr_oi(chain)
        self.skew = skew(chain)
        self.event = event_risk(chain)
        self.crush = iv_crush_warning(chain, history_iv=self.iv_history or None)
        self.unusual = unusual_activity(chain, prev_chain=prev_chain)
        self.prev_chain = prev_chain  # for chain-DYNAMICS factors (per-strike OI-change bias)

        self.atm_iv = self.dist.atm_iv if self.dist else None
        self.iv_rank = iv_rank(self.atm_iv, self.iv_history) if (self.atm_iv and self.iv_history) else None
        self.expected_move = self.dist.expected_move_1sigma if self.dist else None
        self.vrp_ratio = float(SETTINGS.paper_vrp_ratio)

        # --- optional time-series blocks (attached by callers; None => byte-identical legacy path) ---
        # Multi-timeframe momentum: prefer explicit per-timeframe bar/close series; else fall back to a
        # single daily-close series as one timeframe. None when no series supplied (factors abstain).
        self.closes = list(closes) if closes else []
        self.bars_by_tf = dict(bars_by_tf) if bars_by_tf else {}
        self.intraday_session = intraday_session  # {highs, lows, prices, volumes, returns, ...}
        _mtf_input = dict(self.bars_by_tf)
        if not _mtf_input and self.closes:
            _mtf_input = {"1d": self.closes}
        self.momentum: MomentumRead | None = (
            multi_timeframe_momentum(_mtf_input) if _mtf_input else None
        )
        # Options-flow momentum from recorded chain series (OI/GEX/IV-rank/term velocity).
        self.flow: FlowMomentumRead | None = None
        if flow_series:
            kw = {k: v for k, v in flow_series.items() if k in _FLOW_SERIES_KEYS}
            if kw:
                self.flow = flow_momentum(**kw)

    # --- chain navigation ---------------------------------------------------
    def strikes(self) -> list[float]:
        return self.chain.strikes()

    def nearest_strike(self, target: float) -> float | None:
        ks = self.chain.strikes()
        return min(ks, key=lambda k: abs(k - target)) if ks else None

    def atm_strike(self) -> float:
        return self.chain.atm_strike()

    def row(self, strike: float | None, option_type: OptionType) -> ChainRow | None:
        if strike is None:
            return None
        return self.chain.row(strike, option_type)

    def mid(self, strike: float | None, option_type: OptionType) -> float | None:
        """Mid of bid/ask if both present, else LTP. None if the row/price is missing."""
        row = self.row(strike, option_type)
        if row is None:
            return None
        if row.bid and row.ask and row.bid > 0 and row.ask > 0:
            return float((row.bid + row.ask) / 2.0)
        return float(row.ltp) if row.ltp else None

    def leg_liquidity(self, strike: float | None, option_type: OptionType) -> tuple[float, float | None]:
        """Return (open_interest, spread_pct) for a leg. spread_pct is (ask-bid)/mid or None."""
        row = self.row(strike, option_type)
        if row is None:
            return 0.0, None
        spread_pct = None
        if row.bid and row.ask and row.bid > 0 and row.ask > 0:
            mid = (row.bid + row.ask) / 2.0
            if mid > 0:
                spread_pct = float((row.ask - row.bid) / mid)
        return float(row.oi or 0.0), spread_pct

    # --- probability helpers (market-implied) -------------------------------
    def prob_above(self, level: float) -> float | None:
        return self.dist.prob_above(level) if self.dist else None

    def prob_below(self, level: float) -> float | None:
        return self.dist.prob_below(level) if self.dist else None

    def prob_between(self, lo: float, hi: float) -> float | None:
        return self.dist.prob_between(lo, hi) if self.dist else None

    def probability_band(self) -> list[float] | None:
        if self.expected_move is None:
            return None
        return [self.spot - self.expected_move, self.spot + self.expected_move]

    # --- physical-measure helpers (variance risk premium) -------------------
    # Realized moves run ~vrp_ratio of implied, so a rupee level sits FURTHER out in physical-sigma
    # terms. We map the level's distance-from-spot by 1/vrp_ratio and read it off the (risk-neutral)
    # RND — turning a fair-priced probability into the tradeable, real-world edge sellers harvest.
    def _phys(self, level: float) -> float:
        if not self.vrp_ratio or self.vrp_ratio <= 0:
            return level
        return self.spot + (level - self.spot) / self.vrp_ratio

    def prob_above_physical(self, level: float) -> float | None:
        return self.prob_above(self._phys(level))

    def prob_below_physical(self, level: float) -> float | None:
        pa = self.prob_above_physical(level)
        return None if pa is None else max(0.0, 1.0 - pa)

    def prob_between_physical(self, lo: float, hi: float) -> float | None:
        return self.prob_between(self._phys(lo), self._phys(hi))
