"""NSE/BSE trading calendar + the SEBI regime breaks a backtest must not pool across.

Two jobs:

1. **Holiday gating** — the "holiday calendar hook" ``clock.py`` reserved. Source of truth is
   ``data/nse_holidays.csv`` (operator-updatable with the exchange's official list); a high-confidence
   national-holiday seed is embedded so gating works before the CSV is filled. Weekends are always shut.

2. **Regime-break metadata** (research §5) — the F&O landscape changed twice, and pooling a backtest
   across either break certifies a product that no longer trades:
     * **2024-11-20** — NSE discontinued BankNifty/FinNifty/Midcap/NiftyNxt50 **weekly** options
       (BankNifty is monthly-expiry only since). Pre-break weekly cells describe a dead product.
     * **2025-09-01** — NSE weekly expiry moved **Thursday → Tuesday**; BSE (SENSEX/BANKEX) sits Thursday.
"""

from __future__ import annotations

import csv
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

# --- Regime breaks (research §5) -------------------------------------------------------------------
WEEKLY_DISCONTINUED_DATE = date(2024, 11, 20)  # BankNifty/FinNifty/Midcap/NiftyNxt50 weeklies end
NSE_EXPIRY_SHIFT_DATE = date(2025, 9, 1)       # NSE weekly expiry Thu → Tue (BSE stays Thu)
_WEEKLY_DISCONTINUED = frozenset({"BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"})

# High-confidence national NSE/BSE closures (markets always shut). The operator extends the FULL
# exchange holiday list via data/nse_holidays.csv; this seed only prevents obviously-wrong gap flags.
_HOLIDAY_SEED: dict[str, str] = {
    "2024-01-26": "Republic Day", "2024-03-08": "Mahashivratri", "2024-03-25": "Holi",
    "2024-03-29": "Good Friday", "2024-08-15": "Independence Day", "2024-10-02": "Gandhi Jayanti",
    "2024-11-15": "Guru Nanak Jayanti", "2024-12-25": "Christmas",
    "2025-02-26": "Mahashivratri", "2025-03-14": "Holi", "2025-03-31": "Id-ul-Fitr",
    "2025-04-14": "Ambedkar Jayanti", "2025-04-18": "Good Friday", "2025-05-01": "Maharashtra Day",
    "2025-08-15": "Independence Day", "2025-08-27": "Ganesh Chaturthi", "2025-10-02": "Gandhi Jayanti",
    "2025-10-21": "Diwali", "2025-11-05": "Guru Nanak Jayanti", "2025-12-25": "Christmas",
    "2026-01-26": "Republic Day", "2026-08-15": "Independence Day", "2026-10-02": "Gandhi Jayanti",
    "2026-12-25": "Christmas",
}


def _holidays_csv() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "nse_holidays.csv"


@lru_cache(maxsize=1)
def load_holidays() -> dict[str, str]:
    """Merged holiday map ``{iso_date: name}``: embedded seed + ``data/nse_holidays.csv`` override.
    Cached — call ``load_holidays.cache_clear()`` after editing the CSV in a long-running process."""
    out = dict(_HOLIDAY_SEED)
    p = _holidays_csv()
    if p.exists():
        with open(p, newline="", encoding="utf-8") as fh:
            for row in csv.reader(fh):
                if not row or row[0].strip().startswith("#") or row[0].strip().lower() == "date":
                    continue
                out[row[0].strip()] = (row[1].strip() if len(row) > 1 else "holiday")
    return out


def is_holiday(d: date) -> bool:
    return d.isoformat() in load_holidays()


def is_trading_day(d: date) -> bool:
    """Mon–Fri and not a known exchange holiday."""
    return d.weekday() < 5 and not is_holiday(d)


def trading_days(start: date, end: date) -> list[date]:
    """Ascending list of trading days in ``[start, end]`` (holiday-aware)."""
    out, d = [], start
    while d <= end:
        if is_trading_day(d):
            out.append(d)
        d += timedelta(days=1)
    return out


# --- Regime breaks ---------------------------------------------------------------------------------
def weekly_discontinued(underlying: str, on: date) -> bool:
    """True iff ``underlying`` has NO weekly options on ``on`` (post-2024-11-20 for the affected set)."""
    return on >= WEEKLY_DISCONTINUED_DATE and underlying.upper() in _WEEKLY_DISCONTINUED


def expiry_weekday(on: date, exchange: str = "NSE") -> int:
    """Weekly-expiry weekday (Mon=0): BSE→Thursday; NSE→Thursday pre-shift, Tuesday from 2025-09-01."""
    if exchange.upper() == "BSE":
        return 3  # Thursday
    return 1 if on >= NSE_EXPIRY_SHIFT_DATE else 3  # NSE: Tuesday from the shift, else Thursday


def expiry_regime(on: date) -> str:
    """A coarse regime tag so a backtest cell never pools across a SEBI break (research §5)."""
    if on < WEEKLY_DISCONTINUED_DATE:
        return "nse_thu_all_weeklies"   # multi-index weeklies, Thursday expiry
    if on < NSE_EXPIRY_SHIFT_DATE:
        return "nse_thu_nifty_weekly"   # NIFTY-only weekly, Thursday expiry
    return "nse_tue_nifty_weekly"       # NIFTY-only weekly, Tuesday expiry
