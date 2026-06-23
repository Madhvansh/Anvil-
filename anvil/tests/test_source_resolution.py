"""The demo-vs-live decision: it follows the connected broker tokens, and when it falls back to
demo it says WHY. Regression cover for the 'connected a broker but it still shows demo, silently'
bug — see anvil/ingest/source.py."""

from __future__ import annotations

from types import SimpleNamespace

import anvil.ingest as ingest
import anvil.ingest.source as src
from fastapi.testclient import TestClient

from anvil.api.app import app


def _settings(primary: str) -> SimpleNamespace:
    """A SETTINGS stand-in with no env tokens, so token presence is driven by _has_token alone."""
    return SimpleNamespace(
        primary_data_source=primary,
        upstox_access_token=None,
        dhan_access_token=None,
        groww_access_token=None,
        groww_api_key=None,
        groww_totp_seed=None,
        groww_api_secret=None,
    )


def test_demo_default_pins_demo_with_actionable_reason(monkeypatch):
    monkeypatch.setattr(src, "SETTINGS", _settings("demo"))
    monkeypatch.setattr(src, "connected_brokers", lambda: [])
    conn, st = src.pick_connector()
    assert st.mode == "demo" and st.resolved == "demo"
    assert "ANVIL_PRIMARY_SOURCE" in (st.reason or "")  # tells you exactly how to go live


def test_requested_broker_not_connected_falls_back_with_reason(monkeypatch):
    monkeypatch.setattr(src, "SETTINGS", _settings("upstox"))
    monkeypatch.setattr(src, "_has_token", lambda b: False)  # nothing connected
    conn, st = src.pick_connector()
    assert st.mode == "demo"
    assert "Upstox is not connected" in (st.reason or "")


def test_goes_live_when_requested_broker_has_token(monkeypatch):
    monkeypatch.setattr(src, "SETTINGS", _settings("upstox"))
    monkeypatch.setattr(src, "_has_token", lambda b: b == "upstox")
    monkeypatch.setattr(ingest, "get_connector", lambda name=None: SimpleNamespace(name=name))
    conn, st = src.pick_connector()
    assert st.mode == "live" and st.resolved == "upstox" and conn.name == "upstox"


def test_auto_uses_other_connected_broker_when_primary_absent(monkeypatch):
    # Primary is upstox (no token), but groww IS connected → fall through to groww, go live.
    monkeypatch.setattr(src, "SETTINGS", _settings("upstox"))
    monkeypatch.setattr(src, "_has_token", lambda b: b == "groww")
    monkeypatch.setattr(ingest, "get_connector", lambda name=None: SimpleNamespace(name=name))
    conn, st = src.pick_connector()
    assert st.mode == "live" and st.resolved == "groww"


def test_groww_sdk_missing_reports_docker_hint(monkeypatch):
    # groww connected but its SDK can't build (Python 3.14 / no growwapi) → demo, with the hint.
    monkeypatch.setattr(src, "SETTINGS", _settings("upstox"))
    monkeypatch.setattr(src, "_has_token", lambda b: b == "groww")

    def boom(name=None):
        raise RuntimeError("growwapi not installed (the SDK targets Python <=3.13).")

    monkeypatch.setattr(ingest, "get_connector", boom)
    conn, st = src.pick_connector()
    assert st.mode == "demo"
    assert "growwapi" in (st.reason or "").lower()
    assert any(a["broker"] == "groww" and not a["ok"] for a in st.attempts)


def test_source_status_endpoint_reports_demo_in_test_env():
    # No ANVIL_PRIMARY_SOURCE in the test env → demo, and the payload carries the reason field.
    j = TestClient(app).get("/api/source/status").json()
    assert j["mode"] == "demo"
    assert "fallback_reason" in j and "connected_brokers" in j


def test_cached_analyze_cascades_past_a_failing_primary(monkeypatch):
    """The core fall-through fix: when the PRIMARY broker builds but fails AT FETCH time (e.g. Groww
    'Access forbidden — no market-data role'), cached_analyze must try the NEXT connected broker
    (Upstox) and serve LIVE — not drop straight to demo. Regression for 'Upstox works but the app
    shows demo because Groww was primary'."""
    from types import SimpleNamespace

    import anvil.api.deps as deps
    import anvil.ingest as ingest
    from anvil.api.cache import ANALYZE_CACHE
    from anvil.ingest.demo import DemoConnector

    ANALYZE_CACHE.clear()
    fake = SimpleNamespace(primary_data_source="groww")
    monkeypatch.setattr(deps, "SETTINGS", fake)
    monkeypatch.setattr(src, "SETTINGS", fake)
    monkeypatch.setattr(src, "_has_token", lambda b: b in ("groww", "upstox"))

    demo = DemoConnector()

    class FailingGroww:
        name = "groww"

        def get_chain(self, u, e=None):
            raise RuntimeError("Access Forbidden — your API token does not have the required roles")

    class WorkingUpstox:
        name = "upstox"

        def get_chain(self, u, e=None):
            return demo.get_chain(u, e)  # a real chain so analyze_chain is happy

    monkeypatch.setattr(
        ingest, "get_connector",
        lambda name=None: {"groww": FailingGroww(), "upstox": WorkingUpstox()}.get(name, demo),
    )

    payload, _ = deps.cached_analyze("NIFTY")
    prov = payload["provenance"]
    assert prov["mode"] == "live" and prov["source"] == "upstox"
    assert prov["fallback_reason"] is None
    ANALYZE_CACHE.clear()


def test_cached_analyze_demo_with_reason_when_all_live_candidates_fail(monkeypatch):
    """When every connected broker fails to serve a chain, degrade to demo and surface a reason."""
    from types import SimpleNamespace

    import anvil.api.deps as deps
    import anvil.ingest as ingest
    from anvil.api.cache import ANALYZE_CACHE

    ANALYZE_CACHE.clear()
    fake = SimpleNamespace(primary_data_source="upstox")
    monkeypatch.setattr(deps, "SETTINGS", fake)
    monkeypatch.setattr(src, "SETTINGS", fake)
    monkeypatch.setattr(src, "_has_token", lambda b: b == "upstox")

    def boom(name=None):
        raise RuntimeError("token rejected")

    monkeypatch.setattr(ingest, "get_connector", boom)

    payload, _ = deps.cached_analyze("NIFTY")
    prov = payload["provenance"]
    assert prov["mode"] == "demo"
    assert prov["fallback_reason"]
    ANALYZE_CACHE.clear()
