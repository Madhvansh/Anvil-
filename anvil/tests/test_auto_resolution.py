"""Phase 5 — automatic resolution (live/closes.realized_closes_for): the keystone that lets the moat
clock accrue a live track record without the operator hand-feeding realized closes. Strict source
ladder (archive → yahoo → after-close spot), causal (omit what isn't published), never VIX."""

import anvil.live.closes as closes
from anvil.live.closes import realized_closes_for, realized_closes_with_sources


def test_resolver_yahoo_close(monkeypatch):
    monkeypatch.setattr(closes.yahoo, "read_cache",
                        lambda sym: [{"date": "2026-06-20", "o": 1, "h": 1, "l": 1, "c": 24050.0, "volume": 1}]
                        if sym == "^NSEI" else [])
    out = realized_closes_for(["NIFTY", "BANKNIFTY"], "2026-06-20", allow_spot_fallback=False)
    assert out == {"NIFTY": 24050.0}  # BANKNIFTY has no published close → omitted, never guessed


def test_resolver_prefers_archive(monkeypatch):
    class _Archive:
        def index_close_on(self, d, u):
            return 50000.0 if u == "BANKNIFTY" else None

        def equity_close_on(self, d, u):
            return None

    monkeypatch.setattr(closes.yahoo, "read_cache", lambda sym: [])
    out = realized_closes_with_sources(["BANKNIFTY"], "2026-06-20", archive=_Archive(),
                                       allow_spot_fallback=False)
    assert out == {"BANKNIFTY": (50000.0, "bhavcopy")}


def test_resolver_never_settles_against_vix(monkeypatch):
    monkeypatch.setattr(closes.yahoo, "read_cache",
                        lambda sym: [{"date": "2026-06-20", "o": 1, "h": 1, "l": 1, "c": 15.0, "volume": 1}])
    assert realized_closes_for(["INDIAVIX"], "2026-06-20", allow_spot_fallback=False) == {}


def test_resolver_omits_unsettled_day(monkeypatch):
    # The cache has only an earlier day → resolving 'today' before its close yields nothing (causal).
    monkeypatch.setattr(closes.yahoo, "read_cache",
                        lambda sym: [{"date": "2026-06-19", "o": 1, "h": 1, "l": 1, "c": 24000.0, "volume": 1}])
    assert realized_closes_for(["NIFTY"], "2026-06-20", allow_spot_fallback=False) == {}
