"""Connector hardening that is verifiable offline:
  * the market forward is recovered from put-call parity (so live Greeks use a real forward,
    not a cost-of-carry guess);
  * positions merge across brokers into one unified book.
"""

import pytest

from anvil.engine.forward import forward_from_parity, resolve_forward
from anvil.engine.portfolio import beta_weighted_greeks
from anvil.ingest import gather_positions
from anvil.ingest.base import attach_parity_forward
from anvil.ingest.demo import DemoConnector, demo_positions


def test_parity_forward_recovers_market_forward():
    # On the demo chain, parity at ATM should land very near the demo's spot/forward.
    ch = DemoConnector().get_chain("NIFTY")
    fwd = forward_from_parity(ch)
    assert fwd is not None
    assert fwd == pytest.approx(ch.spot, rel=0.02)


def test_attach_parity_forward_tags_source():
    # Simulate a live source that gave a chain WITHOUT a future price (the common case):
    ch = DemoConnector().get_chain("NIFTY").model_copy(
        update={"future_price": None, "future_price_source": None}
    )
    tagged = attach_parity_forward(ch)
    assert tagged.future_price and tagged.future_price > 0
    assert tagged.future_price_source == "put_call_parity"
    # resolve_forward now uses the real (parity) forward, not derived cost-of-carry
    _f, src = resolve_forward(tagged)
    assert src == "put_call_parity"


def test_attach_parity_forward_keeps_explicit_future():
    ch = DemoConnector().get_chain("NIFTY")
    ch = ch.model_copy(update={"future_price": 99999.0, "future_price_source": "nse_bhavcopy_settle"})
    out = attach_parity_forward(ch)               # explicit future must win over parity
    assert out.future_price == 99999.0
    assert out.future_price_source == "nse_bhavcopy_settle"


def test_gather_positions_merges_across_brokers():
    one = demo_positions()
    merged = gather_positions([DemoConnector(), DemoConnector()])
    assert len(merged) == 2 * len(one)            # two brokers' books combined


def test_unified_book_sums_positions():
    merged = gather_positions([DemoConnector(), DemoConnector()])
    pr = beta_weighted_greeks(merged, benchmark="NIFTY", benchmark_price=24000.0)
    single = beta_weighted_greeks(demo_positions(), benchmark="NIFTY", benchmark_price=24000.0)
    assert pr.net_delta == pytest.approx(2 * single.net_delta)


class _NoPosConnector:
    provides_positions = False


def test_gather_skips_sources_without_positions():
    merged = gather_positions([_NoPosConnector(), DemoConnector()])
    assert len(merged) == len(demo_positions())
