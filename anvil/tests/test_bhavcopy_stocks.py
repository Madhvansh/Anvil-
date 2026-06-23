"""Single-stock bhavcopy parsing: STO/STF rows are kept (not just index F&O), and the UDiFF
``UndrlygPric`` (cash close) + ``NewBrdLotQty`` (lot size) are captured — the data the equities
engine runs on. Indices keep their configured lot; stocks take the true bhavcopy lot."""

from __future__ import annotations

from datetime import date

from anvil.ingest.bhavcopy import build_chains, parse_fo_bhavcopy

# Minimal UDiFF rows: a NIFTY index option, plus RELIANCE stock options + a stock future.
_HEADER = ("TckrSymb,FinInstrmTp,XpryDt,StrkPric,OptnTp,SttlmPric,ClsPric,UndrlygPric,"
           "OpnIntrst,ChngInOpnIntrst,TtlTradgVol,NewBrdLotQty")
_ROWS = [
    "NIFTY,IDO,2026-07-31,24000,CE,300,300,24050,1000,50,500,75",
    "NIFTY,IDO,2026-07-31,24000,PE,250,250,24050,900,40,400,75",
    "NIFTY,IDO,2026-07-31,24100,CE,250,250,24050,800,30,300,75",
    "NIFTY,IDO,2026-07-31,24100,PE,300,300,24050,700,20,200,75",
    "RELIANCE,STO,2026-07-31,1400,CE,40,40,1380,5000,200,300,500",
    "RELIANCE,STO,2026-07-31,1400,PE,55,55,1380,4500,150,250,500",
    "RELIANCE,STO,2026-07-31,1360,CE,55,55,1380,4000,100,220,500",
    "RELIANCE,STO,2026-07-31,1360,PE,40,40,1380,3800,90,210,500",
    "RELIANCE,STF,2026-07-31,,,1385,1385,1380,12000,500,800,500",
]
_CSV = _HEADER + "\n" + "\n".join(_ROWS) + "\n"


def test_index_only_default_drops_stocks():
    rows = parse_fo_bhavcopy(_CSV)  # index_only=True default
    syms = {r.symbol for r in rows}
    assert syms == {"NIFTY"}


def test_universe_keeps_stocks_with_cash_and_lot():
    rows = parse_fo_bhavcopy(_CSV, universe={"RELIANCE"})
    rel = [r for r in rows if r.symbol == "RELIANCE"]
    assert rel, "RELIANCE STO/STF rows must be kept when in the universe"
    assert any(r.is_future for r in rel)  # the STF future parsed
    opt = next(r for r in rel if r.is_option)
    assert opt.underlying_price == 1380.0  # UndrlygPric (cash close)
    assert opt.lot_size == 500            # NewBrdLotQty


def test_build_chains_uses_cash_and_bhav_lot_for_stocks():
    rows = parse_fo_bhavcopy(_CSV, universe={"RELIANCE"})
    chains = build_chains(rows, asof=date(2026, 6, 20), min_strikes=2)
    rel = next(c for c in chains if c.underlying == "RELIANCE")
    assert rel.spot == 1380.0       # exact cash price, not the futures-settle proxy
    assert rel.lot_size == 500      # true stock lot from the bhavcopy
    nifty = next(c for c in chains if c.underlying == "NIFTY")
    assert nifty.lot_size == 75     # index keeps the configured lot
