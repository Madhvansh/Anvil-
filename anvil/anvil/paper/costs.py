"""India F&O cost model + realistic fill pricing for the paper simulator.

Fills cross the quoted spread when bid/ask exist, else apply a mid ± slippage. Charges model the
real Indian F&O cost stack: brokerage + STT + exchange txn + GST + SEBI + stamp. RATES ARE
APPROXIMATE and change periodically (and differ buy-vs-sell, option-vs-future) — they are the
documented v1 defaults and the headline knobs are config-overridable. Validate before trusting P&L.
Pure functions; no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import SETTINGS

# --- statutory/exchange rates (fractions of turnover unless noted) ----------
STT_OPTION_SELL = 0.000625  # STT on options is on the SELL-side premium (0.0625%)
STT_FUTURE_SELL = 0.0002  # STT on futures sell-side turnover (0.02%)
EXCH_TXN_OPTION = 0.00035  # NSE options exchange txn charge (~0.035% of premium)
EXCH_TXN_FUTURE = 0.0000173  # NSE futures exchange txn charge (~0.00173% of notional)
EXCH_TXN_EQUITY = 0.0000297
GST_RATE = 0.18  # GST on (brokerage + exchange txn + sebi)
SEBI_RATE = 0.000001  # ₹10 per crore turnover
STAMP_OPTION_BUY = 0.00003  # stamp duty on BUY-side (0.003% of premium)
STAMP_FUTURE_BUY = 0.00002  # stamp duty on BUY-side futures (0.002% of notional)


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
        return round(self.brokerage + self.stt + self.exchange_txn + self.gst + self.sebi + self.stamp, 4)

    def as_dict(self) -> dict:
        return {
            "brokerage": round(self.brokerage, 4),
            "stt": round(self.stt, 4),
            "exchange_txn": round(self.exchange_txn, 4),
            "gst": round(self.gst, 4),
            "sebi": round(self.sebi, 4),
            "stamp": round(self.stamp, 4),
            "total": self.total,
        }


def fill_price(
    side: str,
    mid: float,
    bid: float | None = None,
    ask: float | None = None,
    slippage_bps: float | None = None,
) -> float:
    """Realistic fill: cross the quoted spread if present, else mid ± slippage (bps of mid)."""
    side = side.upper()
    if bid and ask and bid > 0 and ask > 0 and ask >= bid:
        return float(ask if side == "BUY" else bid)
    bps = SETTINGS.paper_slippage_bps if slippage_bps is None else slippage_bps
    adj = mid * (bps / 10_000.0)
    return float(mid + adj if side == "BUY" else max(0.05, mid - adj))


def charges(
    side: str,
    fill: float,
    qty: int,
    instrument_type: str = "CE",
    brokerage_per_order: float | None = None,
) -> Charges:
    """Charges for one order leg. ``qty`` is the absolute contract quantity (lots * lot_size)."""
    side = side.upper()
    turnover = abs(float(fill) * int(qty))
    brokerage = SETTINGS.paper_brokerage_per_order if brokerage_per_order is None else brokerage_per_order
    is_future = instrument_type.upper() == "FUT"
    is_equity = instrument_type.upper() == "EQ"

    if is_future:
        stt = STT_FUTURE_SELL * turnover if side == "SELL" else 0.0
        exch = EXCH_TXN_FUTURE * turnover
        stamp = STAMP_FUTURE_BUY * turnover if side == "BUY" else 0.0
    elif is_equity:
        stt = 0.001 * turnover  # delivery STT both sides (0.1%) — coarse
        exch = EXCH_TXN_EQUITY * turnover
        stamp = 0.00015 * turnover if side == "BUY" else 0.0
    else:  # option
        stt = STT_OPTION_SELL * turnover if side == "SELL" else 0.0
        exch = EXCH_TXN_OPTION * turnover
        stamp = STAMP_OPTION_BUY * turnover if side == "BUY" else 0.0

    sebi = SEBI_RATE * turnover
    gst = GST_RATE * (brokerage + exch + sebi)
    return Charges(brokerage=brokerage, stt=stt, exchange_txn=exch, gst=gst, sebi=sebi, stamp=stamp)
