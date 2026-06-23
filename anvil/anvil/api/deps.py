"""Shared FastAPI helpers: data-source resolution, the disclaimer, and the cached
analyze path the read endpoints share."""

from __future__ import annotations

from fastapi import Depends, HTTPException

from ..auth.deps import current_user
from ..config import SETTINGS
from ..db.models import User
from ..models import OptionChain
from ..pipeline import analyze_chain
from ..tips.types import TIP_DISCLAIMER as TIP_DISCLAIMER  # re-export for API handlers
from .cache import ANALYZE_CACHE

DISCLAIMER = (
    "Analytics & education only. Not investment advice. "
    "Probabilities are market-implied (risk-neutral)."
)

PAPER_DISCLAIMER = (
    "Paper simulation only — not investment advice. Recommendations are personal research; "
    "fills are modeled (spread/slippage) and margin is SPAN-lite. Real execution stays gated."
)

def require_paper_trading(user: User = Depends(current_user)) -> User:
    """Gate the whole /api/paper surface behind the PAPER_TRADING flag + login (owner)."""
    if not SETTINGS.paper_trading:
        raise HTTPException(status_code=403, detail="Paper trading is disabled (PAPER_TRADING=false).")
    return user


def require_tips(user: User = Depends(current_user)) -> User:
    """Gate the whole /api/tips surface behind the TIPS_ENABLED flag + login."""
    if not SETTINGS.tips_enabled:
        raise HTTPException(status_code=403, detail="Tips are disabled (TIPS_ENABLED=false).")
    return user


def get_source():
    """Resolve the best connector by which broker tokens are actually connected (see
    ``ingest.source.pick_connector``); fall back to the offline demo connector when no live
    source is available. Provenance on every payload still reports the REAL source, so this
    degrades gracefully — it never presents demo data as live — and the app keeps working."""
    from ..ingest.source import pick_connector

    conn, _status = pick_connector()
    return conn


def source_status(underlying: str = "NIFTY") -> dict:
    """The live-vs-demo status the UI shows: resolved source, mode, and — when on demo — the
    precise reason + connected brokers. Reflects the SAME decision the dashboard sees, including
    a live source that failed at fetch time (it reuses the cached analyze path)."""
    payload, _ = cached_analyze(underlying)
    prov = payload.get("provenance", {})
    return {
        "mode": prov.get("mode"),
        "source": prov.get("source"),
        "requested_source": prov.get("requested_source"),
        "fallback_reason": prov.get("fallback_reason"),
        "connected_brokers": prov.get("connected_brokers", []),
        "as_of": prov.get("as_of"),
    }


def cached_analyze(underlying: str, expiry: str | None = None) -> tuple[dict, OptionChain]:
    """Return (payload, chain) of PUBLIC market analytics, memoized ~TTL by (source, underlying,
    expiry). Positions are deliberately excluded here — this payload is served by unauthenticated
    market endpoints, so user-scoped position data must never enter it. Position-bearing analytics
    (portfolio risk, scenario, Monte Carlo) fetch their own positions behind current_user.

    The live-vs-demo decision settles here. We try EACH connected chain broker in priority order
    (``ingest.source.live_candidates``) and serve the first that returns a chain. A broker that
    fails — whether it can't be BUILT (missing SDK) or fails AT FETCH time (token rejected, no
    market-data role, network) — does NOT strand the instance on demo: we record the reason and try
    the NEXT connected broker. Only when every live candidate fails do we degrade to demo, stamping
    the precise reason into provenance so the UI can explain why. This is what fixes "Upstox works
    but the app shows demo because the primary (e.g. Groww) built then errored at fetch.\""""
    from ..ingest import get_connector
    from ..ingest.demo import DemoConnector
    from ..ingest.source import connected_brokers, demo_reason, live_candidates

    u = underlying.upper()
    suffix = f"{u}|{expiry or ''}"
    requested = (SETTINGS.primary_data_source or "demo").lower()
    connected = connected_brokers()
    attempts: list[dict] = []

    for broker in live_candidates():
        key = f"{broker}|{suffix}"
        cached = ANALYZE_CACHE.get(key)
        if cached is not None:
            return cached
        try:
            conn = get_connector(broker)
            ch = conn.get_chain(underlying, expiry)
        except Exception as e:  # noqa: BLE001 - this broker failed; try the next connected one
            msg = (str(e) or type(e).__name__).strip()
            attempts.append({"broker": broker, "ok": False, "error": msg[:240]})
            continue
        payload = analyze_chain(ch, None, source=conn.name)
        prov = payload.get("provenance")
        if isinstance(prov, dict):
            prov["requested_source"] = requested
            prov["connected_brokers"] = connected
            prov["fallback_reason"] = None
        result = (payload, ch)
        ANALYZE_CACHE.set(key, result)
        return result

    # No live candidate served a chain → demo, with the precise reason (and per-broker attempts).
    key = f"demo|{suffix}"
    cached = ANALYZE_CACHE.get(key)
    if cached is not None and not attempts:
        return cached
    conn = DemoConnector()
    ch = conn.get_chain(underlying, expiry)
    payload = analyze_chain(ch, None, source=conn.name)
    prov = payload.get("provenance")
    if isinstance(prov, dict):
        prov["requested_source"] = requested
        prov["connected_brokers"] = connected
        prov["fallback_reason"] = demo_reason(attempts)
        if attempts:
            prov["attempts"] = attempts
    result = (payload, ch)
    ANALYZE_CACHE.set(key, result)
    return result


def source_chain_positions(underlying: str, expiry: str | None = None):
    """(connector, chain, positions) for the heavier per-book analytics (scenario/MC).
    Positions come from the connector when it provides them, else demo/empty."""
    conn = get_source()
    ch = conn.get_chain(underlying, expiry)
    positions = conn.get_positions() if conn.provides_positions else []
    return conn, ch, positions
