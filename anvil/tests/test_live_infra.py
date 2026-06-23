"""Phase 3b — live-half foundation: instrument master (real lot sizes + config fallback), the tick
recorder (persist ticks for replay alignment), and the in-process event bus. Offline, no keys."""

from __future__ import annotations

import asyncio

from anvil.ingest.demo import build_demo_chain
from anvil.ingest.instruments import InstrumentMaster
from anvil.live.eventbus import INDEX_TICK, EventBus
from anvil.live.recorder import TickRecorder
from anvil.store import SnapshotStore


def test_instrument_master_lots_and_fallback():
    m = InstrumentMaster.from_records([
        {"name": "NIFTY", "lot_size": 75},
        {"name": "RELIANCE", "lot_size": 500},
        {"name": "BADROW", "lot_size": 0},  # ignored
    ])
    assert m.lot_size("NIFTY") == 75
    assert m.lot_size("RELIANCE") == 500
    assert m.has("RELIANCE") and not m.has("BADROW")
    # Unknown underlying falls back to the config table (BANKNIFTY == 35).
    assert m.lot_size("BANKNIFTY") == 35


def test_instrument_master_kite_csv():
    csv = "tradingsymbol,name,lot_size,segment\nNIFTY24JUN24000CE,NIFTY,75,NFO-OPT\nTCS24JUN,TCS,150,NFO-FUT\n"
    m = InstrumentMaster.from_kite_csv(csv)
    assert m.lot_size("NIFTY") == 75 and m.lot_size("TCS") == 150


def test_tick_recorder_persists(tmp_path):
    store = SnapshotStore(str(tmp_path / "rec.duckdb"))
    rec = TickRecorder(store=store)
    chain = build_demo_chain("NIFTY", spot=24000.0)
    sid = rec.record_chain(chain, "live")
    assert sid and rec.count == 1
    assert store.count("NIFTY") >= 1
    rec.close()


def test_eventbus_pubsub():
    async def body():
        bus = EventBus()
        q = bus.subscribe()
        assert bus.subscriber_count == 1
        delivered = bus.publish(INDEX_TICK, {"underlying": "NIFTY", "ltp": 24000})
        assert delivered == 1
        evt = q.get_nowait()
        assert evt["type"] == INDEX_TICK and evt["ltp"] == 24000
        bus.unsubscribe(q)
        assert bus.subscriber_count == 0

    asyncio.run(body())
