"""The ``Tip`` schema — a public, edge-scored projection of a strategy ``TradeCandidate``.

A Tip carries enough to (a) show a structured trade idea, (b) record a calibratable conviction into
the ledger, and (c) be resolved win/loss after costs. It is a plain dataclass (engine tier, like
``anvil.models`` / ``strategy.types``), serialized through ``engine.util.json_safe``. ``tip_id`` is a
deterministic content hash so re-issuing the same tip is idempotent (mirrors ``ledger.Forecast.id``).

HONESTY: ``conviction`` is a *calibratable* probability — the ledger later checks that tips marked
~65% actually win ~65% of the time, after costs. A Tip never asserts an accuracy/return figure;
any such number is read live from the ledger's tip reliability curve.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from ..engine.util import json_safe

TIP_DISCLAIMER = (
    "Short-term trade idea, not a guarantee. Conviction is a calibrated probability whose live "
    "accuracy is published on the reliability curve — past performance does not assure future "
    "results. Trade only risk capital."
)

# Tier tags — the headline/watchlist split. A tip is "headline" only when the validation gate has
# MEASURED edge for its (structure, regime) cell; everything else tradeable is "watchlist".
HEADLINE = "headline"
WATCHLIST = "watchlist"


@dataclass
class Tip:
    underlying: str
    created_ts: str  # ISO datetime the tip was issued
    resolve_ts: str  # ISO date/datetime the outcome is known (horizon end / expiry)
    horizon_days: float
    structure: str  # = TradeCandidate.strategy (e.g. "iron_condor", "directional_future")
    direction: str  # NEUTRAL/BULLISH/BEARISH/LONG_VOL/SHORT_VOL
    legs: list[dict]  # serialized Leg dicts

    # Edge / conviction (market-implied; calibratable).
    conviction: float  # in [0,1]; recorded as the ledger forecast prob (RAW — the gate tests this)
    edge_prob: float

    # Economics (rupees, all sized units).
    gross_ev: float
    round_trip_cost: float
    cost_adjusted_ev: float
    max_loss: float
    max_profit: float | None
    entry_debit_credit: float
    lot_size: int = 1  # contract size — used for terminal-payoff resolution at expiry
    breakevens: list[float] = field(default_factory=list)
    probability_band: list[float] | None = None

    # Levels (best-effort numeric; may be None when a structure has no single level).
    target: float | None = None
    stop: float | None = None
    target_rule: str = ""
    stop_rule: str = ""

    # Provenance / explainability.
    signals_fired: list[str] = field(default_factory=list)
    regime_at_issue: str = ""  # the raw regime read label (display)
    regime_bucket: str = ""  # the gate bucket (pin_low_vol/trend_high_vol/event_crush/neutral) — the cell key
    tier: str = WATCHLIST
    source: str = "tip_live"  # tip_live | tip_backtest | demo | seed
    rationale: str = ""
    invalidation: str = ""
    model_version: str = "tips-1.0.0"
    ledger_forecast_id: str | None = None
    # Calibration (Phase 2) — DISPLAY only. ``raw_edge_prob`` mirrors the market-implied ``edge_prob``;
    # ``calibrated_edge_prob`` is its calibrated counterpart for the UI / P4 sizing-readiness. The
    # RAW ``conviction`` above (not these) is what the gate's win-rate≥conviction check tests.
    calibrated_edge_prob: float | None = None
    raw_edge_prob: float | None = None
    disclaimer: str = TIP_DISCLAIMER

    @property
    def tip_id(self) -> str:
        """Deterministic content hash — re-issuing the same idea on the same bar is idempotent."""
        key = "|".join(
            [
                self.underlying,
                self.created_ts,
                self.structure,
                self.direction,
                f"{float(self.horizon_days):.4f}",
                self.source,
                json.dumps(self.legs, sort_keys=True, default=str),
            ]
        )
        return hashlib.sha1(key.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        return json_safe(
            {
                "tip_id": self.tip_id,
                "underlying": self.underlying,
                "created_ts": self.created_ts,
                "resolve_ts": self.resolve_ts,
                "horizon_days": self.horizon_days,
                "structure": self.structure,
                "direction": self.direction,
                "legs": self.legs,
                "lot_size": self.lot_size,
                "conviction": self.conviction,
                "edge_prob": self.edge_prob,
                "gross_ev": self.gross_ev,
                "round_trip_cost": self.round_trip_cost,
                "cost_adjusted_ev": self.cost_adjusted_ev,
                "max_loss": self.max_loss,
                "max_profit": self.max_profit,
                "entry_debit_credit": self.entry_debit_credit,
                "breakevens": self.breakevens,
                "probability_band": self.probability_band,
                "target": self.target,
                "stop": self.stop,
                "target_rule": self.target_rule,
                "stop_rule": self.stop_rule,
                "signals_fired": self.signals_fired,
                "regime_at_issue": self.regime_at_issue,
                "regime_bucket": self.regime_bucket,
                "tier": self.tier,
                "source": self.source,
                "rationale": self.rationale,
                "invalidation": self.invalidation,
                "model_version": self.model_version,
                "ledger_forecast_id": self.ledger_forecast_id,
                "calibrated_edge_prob": self.calibrated_edge_prob,
                "raw_edge_prob": self.raw_edge_prob,
                "disclaimer": self.disclaimer,
            }
        )

    def public_dict(self) -> dict:
        """Analytics-safe projection of a Tip: structure/direction/regime/tier only — NO legs,
        targets, ₹ sizing, or risk. The public surface uses this (or omits tips entirely)."""
        return json_safe(
            {
                "underlying": self.underlying,
                "structure": self.structure,
                "direction": self.direction,
                "regime_at_issue": self.regime_at_issue,
                "regime_bucket": self.regime_bucket,
                "tier": self.tier,
                "horizon_days": self.horizon_days,
                "created_ts": self.created_ts,
                "disclaimer": self.disclaimer,
            }
        )


@dataclass
class Prediction:
    """The engine's best current read for ONE underlying — ALWAYS present so the live feed is never
    empty, even when no candidate is tradeable.

    HONESTY (the whole point): ``confidence`` is a documented blend — a sized candidate's calibrated
    ``conviction`` (``edge_prob × regime_fit × iv_factor``) when one exists, else the risk-neutral
    directional probability read straight off the implied distribution — NEVER an asserted win-rate.
    ``edge_verified`` is True ONLY when the validation store has MEASURED, post-cost, out-of-sample
    edge for this ``(structure, regime_bucket, underlying)`` cell (the same verdict the gate reads):
    the ✓ badge is earned, not claimed. ``calibration_reference`` is the nearest live reliability bin
    so the UI can show "when we said ~X%, Y% actually landed" — measured, alongside, never overwriting.
    """

    underlying: str
    as_of: str
    spot: float
    direction: str  # NEUTRAL/BULLISH/BEARISH/LONG_VOL/SHORT_VOL
    confidence: float  # [0,1] honest blend (see confidence_basis)
    confidence_basis: str  # candidate_conviction | rnd_directional | rnd_neutral_band | uninformative
    prob_above: float | None  # RND P(close > spot)
    prob_below: float | None
    expected_move: float | None  # ±1σ rupees (RND)
    target_band: list[float] | None  # [lo, hi] ±1σ levels
    regime: str  # raw regime-read label (display)
    regime_bucket: str  # the gate cell key
    factors: list[dict] = field(default_factory=list)  # FactorSignal dicts (name/fired/active/strength/…)
    best_structure: str | None = None  # the leading candidate's structure (may be NO_TRADE)
    has_actionable_tip: bool = False  # a TRADE candidate cleared the decision policy
    edge_verified: bool = False  # MEASURED headline-eligible cell (earned ✓)
    edge_verified_basis: dict | None = None  # {n, win_rate, t_stat, dsr} when verified or tracking
    calibration_reference: dict | None = None  # nearest live reliability bin {predicted_mean, empirical_freq, count}
    # Calibration (Phase 2) — DISPLAY only, shown ALONGSIDE ``confidence`` (which stays the raw read).
    # ``calibrated_confidence`` is the isotonic/Platt-mapped conviction (None when no map is fit);
    # ``raw_confidence`` is the unmapped number, so the UI can show calibrated-vs-raw.
    calibrated_confidence: float | None = None
    raw_confidence: float | None = None
    # Innovation I.4 — meta-label ACT probability P(this call is correct), DISPLAY-ONLY analytics (public
    # safe: it is a calibrated quality read, not a sized/actionable artifact). None until the meta-label
    # is trained on enough resolved history (cold-start abstains).
    act_probability: float | None = None
    actionable_tip: dict | None = None  # the best tradeable tip dict, when has_actionable_tip (OWNER)
    summary: str = ""  # one-line plain-language read
    disclaimer: str = TIP_DISCLAIMER
    # Phase 4 — per-ticket risk distribution (OWNER-only; position-level sized risk artifacts).
    # ``risk_distribution`` is the mc_pnl risk map (percentiles, VaR/CVaR — risk-neutral, a risk map
    # NOT a return forecast); ``risk_of_ruin`` + ``forward_drawdown`` come from the repeated-bet MC.
    risk_distribution: dict | None = None
    risk_of_ruin: float | None = None
    forward_drawdown: dict | None = None
    roe_overlay: dict | None = None  # win/loss return-on-equity + breakeven (OWNER-only)

    def to_dict(self, *, owner: bool = False) -> dict:
        """Serialize the prediction. ``owner=False`` (default, fail-closed) is the PUBLIC,
        ADR-0004-clean analytics projection: calibrated probabilities / ranges / regime read, with NO
        actionable tip, no sized legs, and no position-level risk distribution. ``owner=True`` adds the
        actionable, sized, distribution-bearing fields — emitted only behind the Phase-4 hard wall."""
        d = {
            "underlying": self.underlying,
            "as_of": self.as_of,
            "spot": self.spot,
            "direction": self.direction,
            "confidence": self.confidence,
            "confidence_basis": self.confidence_basis,
            "prob_above": self.prob_above,
            "prob_below": self.prob_below,
            "expected_move": self.expected_move,
            "target_band": self.target_band,
            "regime": self.regime,
            "regime_bucket": self.regime_bucket,
            "factors": self.factors,
            "best_structure": self.best_structure,
            "edge_verified": self.edge_verified,
            "edge_verified_basis": self.edge_verified_basis,
            "calibration_reference": self.calibration_reference,
            "calibrated_confidence": self.calibrated_confidence,
            "raw_confidence": self.raw_confidence,
            "act_probability": self.act_probability,
            "summary": self.summary,
            "disclaimer": self.disclaimer,
            # Owner-only fields are present as keys but null on the public surface (stable schema).
            "has_actionable_tip": self.has_actionable_tip if owner else False,
            "actionable_tip": self.actionable_tip if owner else None,
            "risk_distribution": self.risk_distribution if owner else None,
            "risk_of_ruin": self.risk_of_ruin if owner else None,
            "forward_drawdown": self.forward_drawdown if owner else None,
            "roe_overlay": self.roe_overlay if owner else None,
        }
        return json_safe(d)

    def public_dict(self) -> dict:
        """The ADR-0004-clean analytics projection (no actionable/sized/risk-distribution fields)."""
        return self.to_dict(owner=False)
