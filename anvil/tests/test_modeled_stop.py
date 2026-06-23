"""Phase 5 — honest modeled-stop resolution (tips/resolve.settle_with_modeled_stop).

The v2 adversary-#2 rule: a naked structure books the WORSE of (stop, true settlement) so a >3σ gap
that breached the stop intraday isn't flattered by a benign close; with no path it degrades to the
exact ``terminal_payoff`` (so existing resolution stays byte-identical)."""

from anvil.tips.resolve import settle_with_modeled_stop, terminal_payoff


def _short_call(strike=24000.0, ref=120.0, lots=1):
    return [{"side": "SELL", "lots": lots, "strike": strike, "option_type": "CE",
             "instrument_type": "CE", "ref_price": ref}]


def test_path_none_equals_terminal_payoff():
    legs = _short_call()
    r = settle_with_modeled_stop(legs, 75, 24050.0, max_loss=5000.0, defined_risk=False, path=None)
    assert r["pnl_final"] == r["pnl_settle"] == round(terminal_payoff(legs, 75, 24050.0), 2)
    assert r["stop_hit"] is False


def test_naked_books_worse_of_stop_and_settlement():
    # Short call settles in profit at 24050 (₹5,250) but the path spiked to 25,000 → breached the stop.
    legs = _short_call(strike=24000.0, ref=120.0)
    r = settle_with_modeled_stop(legs, 75, 24050.0, max_loss=3000.0, defined_risk=False,
                                 path=[(24000.0, 25000.0)])
    assert r["stop_hit"] is True
    assert r["pnl_final"] == -3000.0  # worse of stop (−3000) and settlement (+5250)
    assert r["mae"] < 0  # the spike is recorded


def test_defined_risk_books_the_stop():
    legs = _short_call()
    r = settle_with_modeled_stop(legs, 75, 24050.0, max_loss=3000.0, defined_risk=True,
                                 path=[(24000.0, 25000.0)])
    assert r["stop_hit"] is True
    assert r["pnl_final"] == -3000.0  # defined-risk: the wings bound the loss at the stop


def test_no_breach_books_settlement():
    legs = _short_call(strike=24000.0, ref=120.0)
    r = settle_with_modeled_stop(legs, 75, 24050.0, max_loss=100000.0, defined_risk=False,
                                 path=[(23900.0, 24100.0)])
    assert r["stop_hit"] is False
    assert r["pnl_final"] == r["pnl_settle"]
