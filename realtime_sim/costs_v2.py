"""India F&O transaction-cost stack + realistic fills for Anvil Live v2 (pure stdlib).

Ported from anvil/paper/costs.py and made deliberately CONSERVATIVE: the options STT
sell-side rate is the CURRENT 0.10% of premium (raised from 0.0625% effective 01-Oct-2024),
so paper P&L never flatters a premium-selling strategy by understating its biggest cost.

A "fill" crosses the real quoted spread when bid/ask are present on the live chain (so a
seller is hit on the bid, a buyer lifts the ask — the honest, unfavourable side); otherwise
mid ± slippage. Costs are charged PER LEG PER ORDER, and a round-trip is open + close.

Rates change periodically and differ buy-vs-sell / option-vs-future. These are documented
2026 defaults; validate before trusting any P&L. Read-only — nothing here places an order.
"""
from __future__ import annotations

from dataclasses import dataclass

import config

# --- statutory / exchange rates (fractions of turnover unless noted) --------
STT_OPTION_SELL = 0.0010      # STT on options SELL-side premium — CURRENT 0.10% (was 0.0625%)
STT_FUTURE_SELL = 0.0002      # STT on futures sell-side turnover (0.02%)
EXCH_TXN_OPTION = 0.00035     # NSE options exchange txn charge (~0.035% of premium)
EXCH_TXN_FUTURE = 0.0000173   # NSE futures exchange txn charge
GST_RATE = 0.18              # GST on (brokerage + exchange txn + sebi)
SEBI_RATE = 0.000001          # ₹10 per crore turnover
STAMP_OPTION_BUY = 0.00003    # stamp duty on BUY-side premium (0.003%)
STAMP_FUTURE_BUY = 0.00002    # stamp duty on BUY-side futures notional (0.002%)


@dataclass
class Charges:
    brokerage: float
    stt: float
    exchange_txn: float
    gst: float
    sebi: float
    stamp: float

    @property
    def total(self) -> float:
        return round(self.brokerage + self.stt + self.exchange_txn + self.gst + self.sebi + self.stamp, 2)

    def as_dict(self) -> dict:
        return {"brokerage": round(self.brokerage, 2), "stt": round(self.stt, 2),
                "exchange_txn": round(self.exchange_txn, 2), "gst": round(self.gst, 2),
                "sebi": round(self.sebi, 2), "stamp": round(self.stamp, 2), "total": self.total}


def fill_price(side: str, mid: float, bid: float | None = None, ask: float | None = None,
               slippage_bps: float | None = None) -> float:
    """Realistic fill: cross the quoted spread if present (hit bid to sell, lift ask to buy),
    else mid ± slippage (bps of mid). The unfavourable side, always."""
    side = side.upper()
    if bid and ask and bid > 0 and ask > 0 and ask >= bid:
        return float(ask if side == "BUY" else bid)
    bps = config.V2_SLIPPAGE_BPS if slippage_bps is None else slippage_bps
    adj = mid * (bps / 10_000.0)
    return float(mid + adj if side == "BUY" else max(0.05, mid - adj))


def leg_charges(side: str, fill: float, qty: int, instrument_type: str = "CE",
                brokerage_per_order: float | None = None) -> Charges:
    """Charges for ONE order leg. ``qty`` = absolute contract quantity (lots * lot_size)."""
    side = side.upper()
    turnover = abs(float(fill) * int(qty))
    brokerage = config.V2_BROKERAGE_PER_ORDER if brokerage_per_order is None else brokerage_per_order
    it = instrument_type.upper()
    if it == "FUT":
        stt = STT_FUTURE_SELL * turnover if side == "SELL" else 0.0
        exch = EXCH_TXN_FUTURE * turnover
        stamp = STAMP_FUTURE_BUY * turnover if side == "BUY" else 0.0
    else:  # option (CE/PE)
        stt = STT_OPTION_SELL * turnover if side == "SELL" else 0.0
        exch = EXCH_TXN_OPTION * turnover
        stamp = STAMP_OPTION_BUY * turnover if side == "BUY" else 0.0
    sebi = SEBI_RATE * turnover
    gst = GST_RATE * (brokerage + exch + sebi)
    return Charges(brokerage=brokerage, stt=stt, exchange_txn=exch, gst=gst, sebi=sebi, stamp=stamp)


def round_trip_cost(legs: list[dict], lot_size: int, units: int, settlement_exit: bool = False) -> dict:
    """Total open+close cost for a multi-leg structure of ``units`` lots.

    ``legs`` = [{side, (instrument_type|option_type), entry_fill, exit_fill?}, ...] per-share prices.
    Close reverses the side. Flat brokerage is charged PER ORDER (not scaled by units), turnover
    costs scale with units — so calling with the REAL units keeps EV-time and realized P&L
    consistent (no per-units double-count of brokerage).

    ``settlement_exit=True`` models holding to OPTION EXPIRY: there is no closing TRADE (ITM
    auto-settles, OTM expires worthless), so the close side charges NO brokerage (and no slippage —
    the caller passes intrinsic as exit_fill). Statutory charges on the exit intrinsic still apply.
    """
    qty = int(lot_size) * int(max(units, 1))
    open_c = close_c = 0.0
    for lg in legs:
        side = lg["side"].upper()
        opp = "SELL" if side == "BUY" else "BUY"
        it = lg.get("instrument_type") or lg.get("option_type") or "CE"
        open_c += leg_charges(side, lg["entry_fill"], qty, it).total
        close_brokerage = 0.0 if settlement_exit else None
        close_c += leg_charges(opp, lg.get("exit_fill", lg["entry_fill"]), qty, it,
                               brokerage_per_order=close_brokerage).total
    total = open_c + close_c
    return {"open": round(open_c, 2), "close": round(close_c, 2),
            "total": round(total, 2), "per_unit": round(total / max(units, 1), 2)}
