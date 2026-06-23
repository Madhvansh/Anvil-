"""Phase 1 — the trading calendar (holiday gating) + the two SEBI regime breaks (research §5)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from anvil.live.clock import is_market_open
from anvil.live.trading_calendar import (
    NSE_EXPIRY_SHIFT_DATE,
    WEEKLY_DISCONTINUED_DATE,
    expiry_regime,
    expiry_weekday,
    is_trading_day,
    trading_days,
    weekly_discontinued,
)

IST = timezone(timedelta(hours=5, minutes=30))


def test_weekends_and_holidays_are_not_trading_days():
    assert not is_trading_day(date(2025, 1, 4))   # Saturday
    assert not is_trading_day(date(2025, 1, 5))   # Sunday
    assert not is_trading_day(date(2025, 8, 15))  # Independence Day (seed + csv)
    assert is_trading_day(date(2025, 9, 2))       # an ordinary Tuesday


def test_market_open_is_holiday_aware():
    # 10:00 IST on Independence Day must be CLOSED even though it's a weekday.
    assert not is_market_open(datetime(2025, 8, 15, 10, 0, tzinfo=IST))
    assert is_market_open(datetime(2025, 9, 2, 10, 0, tzinfo=IST))      # ordinary trading day, in-session
    assert not is_market_open(datetime(2025, 9, 2, 8, 0, tzinfo=IST))   # before 09:15


def test_trading_days_skips_weekends_and_holidays():
    days = trading_days(date(2025, 8, 14), date(2025, 8, 18))  # Thu, Fri(holiday), Sat, Sun, Mon
    assert days == [date(2025, 8, 14), date(2025, 8, 18)]


def test_banknifty_weekly_discontinued_after_break():
    assert not weekly_discontinued("BANKNIFTY", WEEKLY_DISCONTINUED_DATE - timedelta(days=1))
    assert weekly_discontinued("BANKNIFTY", WEEKLY_DISCONTINUED_DATE)
    assert weekly_discontinued("FINNIFTY", date(2025, 6, 1))
    assert not weekly_discontinued("NIFTY", date(2025, 6, 1))  # NIFTY keeps its weekly


def test_nse_expiry_weekday_shifts_thu_to_tue():
    assert expiry_weekday(NSE_EXPIRY_SHIFT_DATE - timedelta(days=1), "NSE") == 3  # Thursday
    assert expiry_weekday(NSE_EXPIRY_SHIFT_DATE, "NSE") == 1                      # Tuesday
    assert expiry_weekday(date(2026, 1, 1), "BSE") == 3                           # BSE stays Thursday


def test_expiry_regime_partitions_at_both_breaks():
    assert expiry_regime(date(2024, 1, 1)) == "nse_thu_all_weeklies"
    assert expiry_regime(date(2025, 1, 1)) == "nse_thu_nifty_weekly"
    assert expiry_regime(date(2025, 10, 1)) == "nse_tue_nifty_weekly"
    # the three tags are distinct → a cell keyed on them never pools across a break
    assert len({expiry_regime(date(2024, 1, 1)), expiry_regime(date(2025, 1, 1)),
                expiry_regime(date(2025, 10, 1))}) == 3
