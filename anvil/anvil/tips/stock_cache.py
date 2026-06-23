"""Process-wide TTL cache for the live stock-tips feed (served by /api/tips/equities).

Computing the feed fetches one live chain per universe name, so it is cached for
``stock_refresh_ttl_s`` and recomputed on demand when stale (the supervisor can also keep it warm).
Resilient by construction:
  * if the live compute yields nothing (every chain errored — e.g. a dead session), serve the last
    good cache (flagged stale), else fall back to the legacy EOD store read;
  * market-closed is not special-cased — Upstox returns the last-traded chain, so the feed stays
    populated with an honest ``computed_ts`` (the owner's "show freshest available, timestamped").
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from ..config import SETTINGS
from .types import TIP_DISCLAIMER

_LOCK = threading.Lock()
_CACHE: dict = {"payload": None, "computed_ts": None}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fresh(ts: str | None, ttl: int) -> bool:
    if not ts:
        return False
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(ts)).total_seconds()
    except ValueError:
        return False
    return age < ttl


def _open(factory):
    try:
        return factory()
    except Exception:  # noqa: BLE001 - overlay store best-effort
        return None


def _legacy_fallback() -> dict | None:
    """The pre-rebuild read: most-recent issued equity tip per symbol from the store. Used only when
    the live engine produces nothing, so the feed degrades to last-known instead of going blank."""
    from ..ledger.ledger import CalibrationLedger
    from .equities import EQUITY_STRUCTURE
    from .store import IssuedTipStore

    store = _open(IssuedTipStore)
    if store is None:
        return None
    led = _open(CalibrationLedger)
    try:
        recent = store.recent(limit=400)
        seen: set[str] = set()
        latest: list[dict] = []
        for t in recent:
            if t.get("structure") != EQUITY_STRUCTURE or t["underlying"] in seen:
                continue
            seen.add(t["underlying"])
            latest.append(t)
        buys = [t for t in latest if t["direction"] == "bullish"]
        sells = [t for t in latest if t["direction"] == "bearish"]
        return {
            "buys": sorted(buys, key=lambda t: -(t.get("conviction") or 0)),
            "sells": sorted(sells, key=lambda t: -(t.get("conviction") or 0)),
            "as_of": latest[0]["created_ts"] if latest else None,
            "universe": [t["underlying"] for t in latest],
            "errors": [],
            "tip_calibration": (led.metrics_for_tips() if led is not None else {}),
            "source": "tip_backtest",
            "live": False,
            "stale": True,
            "disclaimer": TIP_DISCLAIMER,
        }
    finally:
        store.close()
        if led is not None:
            led.close()


def _compute() -> dict:
    """Run the dynamic universe through the live full-stack stock predictor."""
    from ..calibration.store import CalibratorStore
    from ..ingest.source import pick_connector
    from ..ledger.ledger import CalibrationLedger
    from .eod import tip_source_for
    from .meta_store import get_meta_label
    from .stocks import rank_universe_live
    from .store import TipValidationStore
    from .universe import select_universe

    conn, _status = pick_connector()
    src = tip_source_for(conn.name)
    universe = select_universe()

    vstore = _open(TipValidationStore)
    led = _open(CalibrationLedger)
    cstore = _open(CalibratorStore)
    try:
        tip_metrics = led.metrics_for_tips() if led is not None else {}
        calibration = None
        if cstore is not None and SETTINGS.calibration_enabled:
            try:
                calibration = cstore.load_service()
            except Exception:  # noqa: BLE001 - display-only overlay
                calibration = None
        try:
            meta_label = get_meta_label()
        except Exception:  # noqa: BLE001
            meta_label = None
        ranked = rank_universe_live(
            universe, conn=conn, source=src, calibration=calibration,
            tip_metrics=tip_metrics, meta_label=meta_label, validation_store=vstore)
    finally:
        for _s in (vstore, led, cstore):
            if _s is not None:
                _s.close()
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    return {
        "buys": ranked["buys"],
        "sells": ranked["sells"],
        "as_of": ranked["as_of"] or _now_iso(),
        "universe": universe,
        "errors": ranked["errors"],
        "tip_calibration": tip_metrics,
        "source": src,
        "live": True,
        "disclaimer": TIP_DISCLAIMER,
    }


def get_stock_tips(*, force: bool = False) -> dict:
    """The live cross-sectional stock-tips feed, TTL-cached. Never raises; degrades to last-cache or
    the legacy store read so the feed is always populated and timestamped."""
    ttl = SETTINGS.stock_refresh_ttl_s
    with _LOCK:
        cur = _CACHE["payload"]
        if not force and cur is not None and _fresh(_CACHE["computed_ts"], ttl):
            return cur
        try:
            payload = _compute()
        except Exception:  # noqa: BLE001 - never sink the feed on a compute error
            if cur is not None:
                return {**cur, "stale": True}
            payload = _legacy_fallback() or {
                "buys": [], "sells": [], "as_of": None, "universe": [], "errors": [],
                "tip_calibration": {}, "source": "demo", "live": False, "stale": True,
                "disclaimer": TIP_DISCLAIMER,
            }
        # Live compute produced no directional names → prefer the last good cache, else legacy.
        if not payload.get("buys") and not payload.get("sells"):
            if cur is not None and (cur.get("buys") or cur.get("sells")):
                return {**cur, "stale": True}
            payload = _legacy_fallback() or payload
        payload["computed_ts"] = _now_iso()
        payload.setdefault("stale", False)
        _CACHE["payload"] = payload
        _CACHE["computed_ts"] = payload["computed_ts"]
        return payload
