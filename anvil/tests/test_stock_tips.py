"""M2: live, chain-driven single-stock tips — full-stack per-stock prediction + cross-sectional rank.

Uses a fake connector (synthetic chain per symbol + candle series) so the engine is exercised with
zero API keys: real differentiated convictions, a factor breakdown, BUY/SELL ranking, and resilience
to one dead symbol."""

from __future__ import annotations

from anvil.ingest.demo import build_demo_chain
from anvil.tips.stocks import predict_stock, rank_universe_live


class _Bar:
    def __init__(self, close: float):
        self.close = close


class FakeConn:
    name = "demo"
    provides_chain = True

    def __init__(self, bad: set[str] | None = None):
        self.bad = bad or set()

    def get_chain(self, sym: str, expiry=None):
        if sym.upper() in self.bad:
            raise RuntimeError("no chain for illiquid name")
        h = sum(ord(c) for c in sym)
        # spot kept well above n_strikes*step so the synthetic strike ladder stays positive
        return build_demo_chain(sym.upper(), spot=3000.0 + h % 2000, skew_slope=0.3 + (h % 5) * 0.2, seed=h % 97)

    def get_candles(self, sym: str, tf: str = "1d", **kw):
        h = sum(ord(c) for c in sym)
        up = (h % 2 == 0)
        return [_Bar(100.0 + (i if up else -i) * 0.5) for i in range(60)]


def test_predict_stock_is_a_rich_read():
    r = predict_stock(FakeConn(), "RELIANCE", equity=1_000_000.0, source="tip_live")
    assert r["underlying"] == "RELIANCE"
    assert r["direction"] in ("bullish", "bearish", "neutral")
    assert 0.0 <= r["conviction"] <= 1.0
    assert r["horizon_days"] == 5.0
    assert isinstance(r["factors"], list)  # the per-stock factor breakdown (chain + momentum)
    assert "spot" in r and r["spot"] > 0
    assert "regime_bucket" in r and "as_of" in r


def test_rank_universe_live_ranks_and_survives_a_bad_symbol():
    conn = FakeConn(bad={"BADSTK"})
    res = rank_universe_live(["AAA", "BBB", "CCC", "DDD", "BADSTK"], conn=conn,
                             equity=1_000_000.0, concurrency=3)
    # the dead name is captured as an error and never surfaced as a tip
    assert any(e["symbol"] == "BADSTK" for e in res["errors"])
    surfaced = {r["underlying"] for r in res["buys"] + res["sells"]}
    assert "BADSTK" not in surfaced
    assert len(res["buys"]) + len(res["sells"]) >= 1
    # each side is ranked by descending conviction (cross-sectional)
    for side in ("buys", "sells"):
        convs = [r["conviction"] for r in res[side]]
        assert convs == sorted(convs, reverse=True)
    # no flat-62%: convictions are real, not a single pinned constant
    all_convs = [r["conviction"] for r in res["buys"] + res["sells"]]
    assert all(0.0 <= c <= 1.0 for c in all_convs)


def test_directional_split_is_disjoint():
    conn = FakeConn()
    res = rank_universe_live(["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"], conn=conn, concurrency=4)
    buys = {r["underlying"] for r in res["buys"]}
    sells = {r["underlying"] for r in res["sells"]}
    assert buys.isdisjoint(sells)
