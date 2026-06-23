"""Phase 1 — exercise the pre-2024 LEGACY bhavcopy layout (SYMBOL/SETTLE_PR/…).

``parse_fo_bhavcopy`` claims dual-layout support but only the modern UDiFF header was tested. This
fixture proves the legacy ``fo{DDMMMYYYY}bhav`` columns parse (so the 24-month backfill, which reaches
pre-July-2024 dates, won't silently drop them)."""

from __future__ import annotations

from datetime import date

from anvil.ingest.bhavcopy import build_chains, parse_fo_bhavcopy
from anvil.models import OptionType

_LEGACY = """INSTRUMENT,SYMBOL,EXPIRY_DT,STRIKE_PR,OPTION_TYP,SETTLE_PR,CLOSE,OPEN_INT,CHG_IN_OI,CONTRACTS
FUTIDX,NIFTY,26-JUN-2025,0,XX,24550.50,24548.00,1234500,5600,98000
OPTIDX,NIFTY,26-JUN-2025,24500,CE,180.25,178.00,450000,12000,34000
OPTIDX,NIFTY,26-JUN-2025,24500,PE,150.10,151.00,520000,-8000,41000
OPTIDX,NIFTY,26-JUN-2025,24600,CE,120.00,119.00,300000,9000,22000
OPTIDX,NIFTY,26-JUN-2025,24600,PE,200.00,201.00,280000,4000,19000
"""


def test_legacy_layout_parses():
    rows = parse_fo_bhavcopy(_LEGACY)
    futs = [r for r in rows if r.is_future]
    opts = [r for r in rows if r.is_option]
    assert len(rows) == 5 and len(futs) == 1 and len(opts) == 4
    assert futs[0].settle == 24550.50
    assert {o.strike for o in opts} == {24500.0, 24600.0}
    assert all(o.expiry == "2025-06-26" for o in opts)  # legacy DD-MON-YYYY → ISO
    ce = next(o for o in opts if o.strike == 24500.0 and o.option_type == OptionType("CE"))
    assert ce.settle == 180.25 and ce.oi == 450000.0


def test_legacy_builds_a_chain():
    chains = build_chains(parse_fo_bhavcopy(_LEGACY), asof=date(2025, 6, 20))
    assert len(chains) == 1
    ch = chains[0]
    assert ch.underlying == "NIFTY" and ch.future_price == 24550.50 and len(ch.rows) == 4
