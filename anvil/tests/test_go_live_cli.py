"""Guard: `anvil go-live` sets the supervisor overrides on the FROZEN Settings without raising
(regression for the FrozenInstanceError that broke go-live)."""

from __future__ import annotations

import uvicorn

import anvil.cli as cli
from anvil.config import SETTINGS


def test_go_live_sets_overrides_on_frozen_settings(monkeypatch):
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: None)  # don't actually start the server
    orig = (SETTINGS.live_supervisor_enabled, SETTINGS.cockpit_force_open, SETTINGS.cockpit_underlyings)
    try:
        ns = cli.build_parser().parse_args(["go-live", "--force-open", "--underlyings", "NIFTY,BANKNIFTY"])
        rc = cli.cmd_go_live(ns)
        assert rc == 0
        assert SETTINGS.live_supervisor_enabled is True
        assert SETTINGS.cockpit_force_open is True
        assert SETTINGS.cockpit_underlyings == "NIFTY,BANKNIFTY"
    finally:
        object.__setattr__(SETTINGS, "live_supervisor_enabled", orig[0])
        object.__setattr__(SETTINGS, "cockpit_force_open", orig[1])
        object.__setattr__(SETTINGS, "cockpit_underlyings", orig[2])
