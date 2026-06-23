"""Token-aware market-data source resolution.

The *demo-vs-live* decision is made HERE, at request time, from the brokers that actually have
a usable token — not from a static env flag baked in at process start. Connecting a broker can
therefore flip the instance to live without a restart, and when we fall back to demo we return a
precise, human-readable *reason* so the UI can explain itself instead of silently degrading.

Resolution order (only brokers that hold a valid token are tried):
  1. the configured ``ANVIL_PRIMARY_SOURCE`` if it is a chain-capable broker,
  2. any other connected chain broker (upstox -> dhan -> groww),
  3. the offline demo connector (with a reason).

``ANVIL_PRIMARY_SOURCE=demo`` (the default) pins demo and does NOT auto-probe broker tokens, so
tests and fresh installs stay hermetic. Set it to your broker (e.g. ``upstox``) to go live.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config import SETTINGS
from .base import Connector
from .demo import DemoConnector

# Brokers that can serve an option chain. Kite is positions-only; demo is the fallback.
_CHAIN_BROKERS: tuple[str, ...] = ("upstox", "dhan", "groww")


@dataclass
class SourceStatus:
    """Why the instance is on the source it's on — the trust surface for the UI."""

    resolved: str  # connector actually in use ("upstox" | "groww" | "demo" | ...)
    mode: str  # "live" | "demo"
    requested: str  # configured ANVIL_PRIMARY_SOURCE
    reason: str | None = None  # set when on demo: WHY, and what to do about it
    connected: list[str] = field(default_factory=list)  # brokers that hold a valid token
    attempts: list[dict] = field(default_factory=list)  # per-broker probe failures

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "source": self.resolved,
            "requested_source": self.requested,
            "fallback_reason": self.reason,
            "connected_brokers": self.connected,
            "attempts": self.attempts,
        }


def _has_token(broker: str) -> bool:
    """True if a usable (unexpired) token exists for ``broker`` — file store or env creds."""
    from ..auth.token_store import TokenStore

    if TokenStore().is_valid(broker):
        return True
    if broker == "upstox":
        return bool(SETTINGS.upstox_access_token)
    if broker == "dhan":
        return bool(SETTINGS.dhan_access_token)
    if broker == "groww":
        return bool(
            SETTINGS.groww_access_token
            or (SETTINGS.groww_api_key and (SETTINGS.groww_totp_seed or SETTINGS.groww_api_secret))
        )
    return False


def connected_brokers() -> list[str]:
    """Chain-capable brokers that currently hold a usable token."""
    return [b for b in _CHAIN_BROKERS if _has_token(b)]


def live_candidates() -> list[str]:
    """Ordered chain-capable brokers to TRY for live data — the configured primary first, then any
    other connected chain broker — restricted to those that actually hold a usable token. Empty when
    ``ANVIL_PRIMARY_SOURCE=demo`` (pins demo, no probing). Single source of truth for the try-order so
    ``pick_connector`` and the request-time fetch loop (``api.deps.cached_analyze``) agree."""
    requested = (SETTINGS.primary_data_source or "demo").lower()
    if requested == "demo":
        return []
    order: list[str] = []
    if requested in _CHAIN_BROKERS:
        order.append(requested)
    for b in _CHAIN_BROKERS:
        if b not in order:
            order.append(b)
    return [b for b in order if _has_token(b)]


def demo_reason(attempts: list[dict] | None = None) -> str:
    """The precise, human-readable reason the instance is on demo right now — used when EVERY live
    candidate failed (at build OR fetch time). Mirrors ``pick_connector``'s messaging so the demo
    banner reads the same whether a broker failed to build or failed to serve a chain."""
    requested = (SETTINGS.primary_data_source or "demo").lower()
    if requested == "demo":
        return (
            "Demo mode (ANVIL_PRIMARY_SOURCE=demo). Set ANVIL_PRIMARY_SOURCE to your broker "
            "(e.g. upstox) and connect it to switch to live data."
        )
    return _demo_reason(requested, connected_brokers(), attempts or [])


def _friendly_error(broker: str, err: Exception) -> str:
    """Turn a connector build/auth exception into a short, actionable message."""
    text = str(err) or type(err).__name__
    low = text.lower()
    if broker == "groww" and ("growwapi" in low or "no module named" in low):
        return "needs the growwapi SDK (Python <=3.13) - run the Docker image to use Groww for data."
    if "token" in low or "expired" in low:
        return "token missing or expired — reconnect."
    return text


def _demo_reason(requested: str, connected: list[str], attempts: list[dict]) -> str:
    """Compose the precise reason we are showing demo data instead of live."""
    parts: list[str] = []
    cap = requested.capitalize()
    if requested in _CHAIN_BROKERS and requested not in connected:
        parts.append(f"{cap} is not connected (no valid token). Click 'Open login' to connect {cap}.")
    for a in attempts:
        parts.append(f"{a['broker'].capitalize()}: {a['error']}")
    if not parts:
        if connected:
            parts.append("Connected broker could not serve live data — showing demo.")
        else:
            parts.append("No broker connected — showing demo data. Connect Upstox to go live.")
    return " ".join(parts)


def pick_connector() -> tuple[Connector, SourceStatus]:
    """Choose the best available connector and report why. Never raises — falls back to demo."""
    requested = (SETTINGS.primary_data_source or "demo").lower()
    connected = connected_brokers()

    # Explicit demo (the default): stay offline, don't probe broker tokens. Keeps tests/fresh
    # installs hermetic. Connecting a broker requires ANVIL_PRIMARY_SOURCE set to that broker.
    if requested == "demo":
        reason = (
            "Demo mode (ANVIL_PRIMARY_SOURCE=demo). Set ANVIL_PRIMARY_SOURCE to your broker "
            "(e.g. upstox) and connect it to switch to live data."
        )
        return DemoConnector(), SourceStatus("demo", "demo", requested, reason=reason, connected=connected)

    # Candidate order (primary first, then other connected brokers; only those holding a token).
    order = live_candidates()

    from . import get_connector

    attempts: list[dict] = []
    for broker in order:
        try:
            conn = get_connector(broker)
        except Exception as e:  # noqa: BLE001 - probe failure; try the next candidate
            attempts.append({"broker": broker, "ok": False, "error": _friendly_error(broker, e)})
            continue
        return conn, SourceStatus(broker, "live", requested, connected=connected, attempts=attempts)

    reason = _demo_reason(requested, connected, attempts)
    return DemoConnector(), SourceStatus("demo", "demo", requested, reason=reason, connected=connected, attempts=attempts)
