"""Pluggable data connectors. All map vendor payloads to anvil.models types."""

from __future__ import annotations

from ..config import SETTINGS
from .base import Connector
from .demo import DemoConnector


def get_connector(name: str | None = None) -> Connector:
    """Return a connector by name, falling back to the configured/default source.

    Live connectors require credentials; if absent we raise a clear error rather
    than silently returning demo data.
    """
    name = (name or SETTINGS.primary_data_source or "demo").lower()
    if name == "demo":
        return DemoConnector()
    if name == "upstox":
        from .upstox import UpstoxConnector

        return UpstoxConnector.from_env()
    if name == "dhan":
        from .dhan import DhanConnector

        return DhanConnector.from_env()
    if name == "groww":
        from .groww import GrowwConnector

        return GrowwConnector.from_env()
    raise ValueError(f"Unknown data source: {name!r} (use demo|upstox|dhan|groww)")


def gather_positions(connectors) -> list:
    """Merge positions across brokers (e.g. Kite + Groww) into one book for the unified
    cross-broker risk view. Connectors that don't provide positions, or that error, are
    skipped — a missing broker degrades the view, it doesn't break it."""
    from ..models import Position  # noqa: F401 - documents the element type

    out: list = []
    for c in connectors:
        if not getattr(c, "provides_positions", False):
            continue
        try:
            out.extend(c.get_positions())
        except Exception:  # noqa: BLE001 - one broker down must not sink the book
            continue
    return out
