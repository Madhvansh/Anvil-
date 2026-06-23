"""Analysis orchestration — turn a chain (+ optional positions) into a full analytics
payload and a storable Snapshot. Shared by the CLI and the API so logic lives once.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .engine import oi as oi_mod
from .engine.gex import compute_gex
from .engine.implied_dist import implied_distribution
from .engine.portfolio import beta_weighted_greeks
from .engine.provenance import provenance
from .engine.regime import read_regime
from .engine.util import json_safe
from .engine.vol import skew
from .models import OptionChain, Position, Snapshot


def analyze_chain(
    chain: OptionChain, positions: list[Position] | None = None, source: str | None = None
) -> dict:
    """Compute the full Phase-1 analytics surface for one chain.

    ``source`` (the connector/source name) is recorded as data provenance so every payload
    declares whether it is live / backtested / demo / derived. Callers that know the source
    (API, snapshot, ledger) pass it; bare engine calls leave it None (mode "derived")."""
    gex = compute_gex(chain)
    dist = implied_distribution(chain)
    regime = read_regime(chain, gex=gex, dist=dist)

    walls = oi_mod.oi_walls(chain, n=3)
    payload: dict = {
        "underlying": chain.underlying,
        "spot": chain.spot,
        "expiry": chain.expiry,
        "timestamp": chain.timestamp,
        "oi": {
            "pcr_oi": oi_mod.pcr_oi(chain),
            "pcr_volume": oi_mod.pcr_volume(chain),
            "max_pain": oi_mod.max_pain(chain),
            "oi_change": oi_mod.total_oi_change(chain),
            "call_resistance": walls.call_resistance,
            "put_support": walls.put_support,
        },
        "gex": {
            "total_gex": gex.total_gex,
            "zero_gamma_flip": gex.zero_gamma_flip,
            "call_walls": gex.call_walls,
            "put_walls": gex.put_walls,
        },
        "implied_distribution": None,
        "skew": skew(chain),
        "regime": {
            "label": regime.label,
            "drivers": regime.drivers,
            "prob_inside_em": regime.prob_inside_em,
        },
        "provenance": provenance(chain, source=source),
    }
    if dist is not None:
        payload["implied_distribution"] = {
            "expected_move_1sigma": dist.expected_move_1sigma,
            "em_straddle": dist.em_straddle,
            "em_atm_iv": dist.em_atm_iv,
            "atm_iv": dist.atm_iv,
            "prob_above_spot": dist.prob_above(chain.spot),
        }

    if positions:
        bench = chain.underlying if chain.underlying in ("NIFTY", "BANKNIFTY") else "NIFTY"
        pr = beta_weighted_greeks(positions, benchmark=bench, benchmark_price=chain.spot)
        payload["portfolio"] = {
            "net_delta": pr.net_delta,
            "net_gamma": pr.net_gamma,
            "net_theta": pr.net_theta,
            "net_vega": pr.net_vega,
            "beta_weighted_delta": pr.beta_weighted_delta,
            "bwd_lots": pr.bwd_lots,
            "benchmark": pr.benchmark,
            "per_position": pr.per_position,
            "notes": pr.notes,
        }

    return json_safe(payload)


def to_snapshot(payload: dict) -> Snapshot:
    dist = payload.get("implied_distribution") or {}
    return Snapshot(
        underlying=payload["underlying"],
        timestamp=payload.get("timestamp") or datetime.now(timezone.utc).isoformat(),
        spot=payload["spot"],
        expiry=payload["expiry"],
        pcr_oi=payload["oi"]["pcr_oi"],
        pcr_volume=payload["oi"]["pcr_volume"],
        max_pain=payload["oi"]["max_pain"],
        total_gex=payload["gex"]["total_gex"],
        zero_gamma_flip=payload["gex"]["zero_gamma_flip"],
        expected_move_1sigma=dist.get("expected_move_1sigma"),
        atm_iv=dist.get("atm_iv"),
        regime=payload["regime"]["label"],
        extra=payload,
    )
