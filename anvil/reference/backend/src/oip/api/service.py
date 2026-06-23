"""Read services backing the API: resolve a snapshot, group legs by strike, attach Greeks.

Resolution policy: an explicit snapshot_id must already exist; otherwise use the latest stored
snapshot for the underlying; if none exists yet, ingest one now (offline fixture) so the first
call works out of the box.
"""

from __future__ import annotations

from ..constants import DISCLAIMER
from ..data.source import ChainRequest, DataSource
from ..pipeline.ingest import ingest
from ..storage.duck import DuckStore
from ..storage.sqlite_meta import SqliteMeta

_FLAG = {"c": "c", "call": "c", "ce": "c", "p": "p", "put": "p", "pe": "p"}


def resolve_snapshot_id(
    underlying: str, snapshot_id: str | None, *, source: DataSource, store: DuckStore, meta: SqliteMeta
) -> str:
    if snapshot_id:
        if meta.get_snapshot(snapshot_id) is None:
            raise KeyError(snapshot_id)
        return snapshot_id
    underlying = underlying.upper()  # canonical symbol (matches normalize/storage)
    existing = meta.latest_snapshot_id(underlying)
    if existing:
        return existing
    return ingest(source, ChainRequest(underlying=underlying), store=store, meta=meta).snapshot_id


def _leg_view(r: dict) -> dict:
    return {
        "option_type": r["option_type"],
        "last_price": r.get("last_price"),
        "bid": r.get("bid"),
        "ask": r.get("ask"),
        "oi": r.get("oi"),
        "volume": r.get("volume"),
        "iv_source": r.get("iv_source"),
        "iv_used": r.get("iv_used"),
        "t_years": r.get("t_years"),
        "theo_price": r.get("price"),
        "delta": r.get("delta"),
        "gamma": r.get("gamma"),
        "theta_per_day": r.get("theta_per_day"),
        "vega_per_pct": r.get("vega_per_pct"),
        "rho": r.get("rho"),
    }


def get_chain_view(
    underlying: str, snapshot_id: str | None = None, *,
    source: DataSource, store: DuckStore, meta: SqliteMeta,
) -> dict:
    sid = resolve_snapshot_id(underlying, snapshot_id, source=source, store=store, meta=meta)
    joined = store.read_chain_with_greeks(sid)
    if not joined:
        raise KeyError(sid)

    head = joined[0]
    # Key by (expiry, strike) so a multi-expiry snapshot never collapses distinct contracts.
    rows_by_key: dict[tuple, dict] = {}
    for r in joined:
        key = (r["expiry"], r["strike"])
        sr = rows_by_key.setdefault(
            key, {"expiry": r["expiry"], "strike": r["strike"], "call": None, "put": None}
        )
        if r["option_type"] == "c":
            sr["call"] = _leg_view(r)
        else:
            sr["put"] = _leg_view(r)

    return {
        "underlying": head["underlying"],
        "snapshot_id": sid,
        "snapshot_ts": head["snapshot_ts"],
        "expiry": head["expiry"],
        "spot": head["spot"],
        "future_price": head["future_price"],
        "future_price_source": head["future_price_source"],
        "risk_free_rate": head["risk_free_rate"],
        "price_model": head.get("price_model") or "black76",
        "engine_version": head.get("engine_version"),
        "rows": [rows_by_key[k] for k in sorted(rows_by_key)],
        "disclaimer": DISCLAIMER,
    }


def get_leg_greeks(
    underlying: str, strike: float, option_type: str, snapshot_id: str | None = None, *,
    source: DataSource, store: DuckStore, meta: SqliteMeta,
) -> dict:
    flag = _FLAG.get(str(option_type).strip().lower())
    if flag is None:
        raise ValueError(f"Unrecognized option_type: {option_type!r}")

    sid = resolve_snapshot_id(underlying, snapshot_id, source=source, store=store, meta=meta)
    joined = store.read_chain_with_greeks(sid)
    match = next(
        (r for r in joined if r["strike"] == float(strike) and r["option_type"] == flag), None
    )
    if match is None:
        raise KeyError(f"No {flag} leg at strike {strike} in snapshot {sid}")

    return {
        "underlying": match["underlying"],
        "snapshot_id": sid,
        "strike": match["strike"],
        "option_type": flag,
        "expiry": match["expiry"],
        "iv_used": match.get("iv_used"),
        "t_years": match.get("t_years"),
        "theo_price": match.get("price"),
        "delta": match.get("delta"),
        "gamma": match.get("gamma"),
        "theta_per_day": match.get("theta_per_day"),
        "vega_per_pct": match.get("vega_per_pct"),
        "rho": match.get("rho"),
        "price_model": match.get("price_model") or "black76",
        "engine_version": match.get("engine_version"),
        "disclaimer": DISCLAIMER,
    }
