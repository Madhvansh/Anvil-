"""Trade-candidate schema for the paper-trading strategy layer.

A ``TradeCandidate`` is the unit the strategy library emits and the paper simulator executes.
It carries the full **decision policy** (entry reason, invalidation, expected value, probability
band, liquidity, volatility risk, time/target/stop, and a "no-trade" score) so every paper
action is explainable. ``edge_prob`` is the **market-implied** probability the defined structure
finishes profitable (straight from the Breeden-Litzenberger distribution) — a *calibratable*
probability, never a price prediction. These are plain dataclasses (engine tier, like
``anvil.models``), not Pydantic, and serialize through ``engine.util.json_safe``.

COMPLIANCE: this module is private to the paper-trading subsystem. It deliberately produces
directional buy/sell structures and must NEVER be wired into the public copilot/analyst surface.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..engine.util import json_safe
from ..models import OptionType

# Decision-policy actions.
TRADE = "trade"
HOLD = "hold"
EXIT = "exit"
REDUCE = "reduce"
HEDGE = "hedge"
NO_TRADE = "no_trade"
ACTIONS = (TRADE, HOLD, EXIT, REDUCE, HEDGE, NO_TRADE)

# Direction tags.
NEUTRAL = "neutral"
BULLISH = "bullish"
BEARISH = "bearish"
LONG_VOL = "long_vol"
SHORT_VOL = "short_vol"


@dataclass
class Leg:
    """One leg of a structure. ``option_type=None`` => a FUT/EQ (linear) leg."""

    side: str  # "BUY" | "SELL"
    lots: int  # absolute number of lots (>=1); sign comes from side
    expiry: str
    ref_price: float  # mark at candidate time (mid or LTP), per unit (premium for options)
    option_type: OptionType | None = None
    strike: float | None = None
    instrument_type: str = "CE"  # "CE" | "PE" | "FUT" | "EQ"
    delta: float | None = None  # per-contract greek snapshot, if known
    symbol: str | None = None

    @property
    def sign(self) -> int:
        return 1 if str(self.side).upper() == "BUY" else -1

    def cashflow(self, lot_size: int) -> float:
        """Signed cash flow to OPEN this leg (positive = cash out / debit)."""
        return self.sign * float(self.ref_price) * int(self.lots) * int(lot_size)

    def to_dict(self) -> dict:
        return json_safe(
            {
                "side": self.side,
                "lots": self.lots,
                "expiry": self.expiry,
                "ref_price": self.ref_price,
                "option_type": self.option_type.value if self.option_type else None,
                "strike": self.strike,
                "instrument_type": self.instrument_type,
                "delta": self.delta,
                "symbol": self.symbol,
            }
        )


@dataclass
class TradeCandidate:
    strategy: str
    underlying: str
    direction: str  # one of NEUTRAL/BULLISH/BEARISH/LONG_VOL/SHORT_VOL
    legs: list[Leg]
    lot_size: int

    # Edge / conviction (market-implied; calibratable).
    edge_prob: float  # P(structure profitable by horizon) in [0,1]
    conviction: float  # edge_prob nudged by regime + IV-rank alignment, in [0,1]

    # Economics (sized totals — scaled by `units` during generation).
    entry_debit_credit: float  # net cash to OPEN (positive = debit/cash out, negative = credit)
    max_loss: float  # modeled worst-case (rupees, all units); finite even for naked (stop/CVaR)
    max_profit: float | None  # None => undefined upside (long options) — allowed; undefined LOSS is not
    breakevens: list[float]
    expected_value: float  # modeled EV in rupees, all units
    horizon_days: float

    # Decision policy.
    entry_reason: str = ""
    invalidation_condition: str = ""
    probability_band: list[float] | None = None  # [lower, upper] index levels (±1σ)
    liquidity_score: float = 0.0  # 0..1
    volatility_risk: str = "medium"  # low | medium | high
    time_stop: float | None = None  # days
    target_exit: str = ""  # human description of the take-profit rule
    stop_exit: str = ""  # human description of the stop rule
    no_trade_score: float = 0.0  # 0..1; high => prefer doing nothing
    action: str = TRADE  # final decision-policy verdict

    # Sizing + rationale + audit.
    units: int = 1  # number of lot-sets actually sized
    sizing: dict = field(default_factory=dict)
    exit_rules: dict = field(default_factory=dict)
    rationale: str = ""
    drivers: dict = field(default_factory=dict)
    score_components: dict = field(default_factory=dict)
    defined_risk: bool = True
    # Risk metadata for Phase 4 honest sizing. ``regime_kind`` ("short_vol"/"long_vol"/"trend")
    # drives the negative-skew Kelly cap; ``tail_loss_per_unit`` is the stress (≈3σ) gap loss for
    # naked structures, fed to the sizing CVaR cap so we size against the gap, not the modeled stop.
    regime_kind: str = ""
    tail_loss_per_unit: float | None = None

    # Calibration (Phase 2) — DISPLAY/sizing-readiness only. ``raw_edge_prob`` mirrors ``edge_prob``
    # (the market-implied number sizing/Kelly still runs off — untouched); ``calibrated_edge_prob`` is
    # the calibrated probability for the same number, exposed for the UI and for P4 sizing to later
    # consume via a strictly walk-forward path. NEVER fed into the gate's certification.
    calibrated_edge_prob: float | None = None
    raw_edge_prob: float | None = None

    @property
    def rank_score(self) -> float:
        """Capital flows to the highest expected-edge-per-rupee-at-risk."""
        if self.max_loss <= 0:
            return 0.0
        return float(self.conviction) * (self.expected_value / self.max_loss)

    def to_dict(self) -> dict:
        return json_safe(
            {
                "strategy": self.strategy,
                "underlying": self.underlying,
                "direction": self.direction,
                "legs": [leg.to_dict() for leg in self.legs],
                "lot_size": self.lot_size,
                "edge_prob": self.edge_prob,
                "conviction": self.conviction,
                "entry_debit_credit": self.entry_debit_credit,
                "max_loss": self.max_loss,
                "max_profit": self.max_profit,
                "breakevens": self.breakevens,
                "expected_value": self.expected_value,
                "horizon_days": self.horizon_days,
                "entry_reason": self.entry_reason,
                "invalidation_condition": self.invalidation_condition,
                "probability_band": self.probability_band,
                "liquidity_score": self.liquidity_score,
                "volatility_risk": self.volatility_risk,
                "time_stop": self.time_stop,
                "target_exit": self.target_exit,
                "stop_exit": self.stop_exit,
                "no_trade_score": self.no_trade_score,
                "action": self.action,
                "units": self.units,
                "sizing": self.sizing,
                "exit_rules": self.exit_rules,
                "rationale": self.rationale,
                "drivers": self.drivers,
                "score_components": self.score_components,
                "defined_risk": self.defined_risk,
                "regime_kind": self.regime_kind,
                "tail_loss_per_unit": self.tail_loss_per_unit,
                "calibrated_edge_prob": self.calibrated_edge_prob,
                "raw_edge_prob": self.raw_edge_prob,
                "rank_score": self.rank_score,
            }
        )
