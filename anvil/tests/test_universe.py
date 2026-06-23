"""M2: dynamic stock-universe selection — liquidity+momentum composite, with a config-floor fallback."""

from __future__ import annotations

from anvil.config import SETTINGS
from anvil.tips import universe as U


def test_select_universe_ranks_by_liquidity_and_momentum(monkeypatch):
    monkeypatch.setattr(U, "_liquidity_pool", lambda screen_n, cache_dir: ["AAA", "BBB", "CCC", "DDD"])
    moms = {"AAA": 0.1, "BBB": 0.9, "CCC": 0.0, "DDD": 0.5}
    monkeypatch.setattr(U, "_momentum_strength", lambda s: moms[s])

    out = U.select_universe(top_n=2, screen_n=4)
    # liquidity_rank: AAA1.0 BBB.75 CCC.5 DDD.25 ; score=.5*liq+.5*mom →
    # AAA.55 BBB.825 CCC.25 DDD.375  → top2 = BBB, AAA
    assert out == ["BBB", "AAA"]


def test_select_universe_falls_back_to_config_floor(monkeypatch):
    monkeypatch.setattr(U, "_liquidity_pool", lambda screen_n, cache_dir: [])
    monkeypatch.setattr(U, "_instrument_pool", lambda screen_n: [])

    out = U.select_universe(top_n=3)
    floor = [s.strip().upper() for s in SETTINGS.stock_options_universe.split(",") if s.strip()][:3]
    assert out == floor
    assert len(out) == 3


def test_select_universe_never_empty(monkeypatch):
    monkeypatch.setattr(U, "_liquidity_pool", lambda screen_n, cache_dir: [])
    monkeypatch.setattr(U, "_instrument_pool", lambda screen_n: [])
    assert U.select_universe(top_n=5)  # config floor guarantees non-empty
