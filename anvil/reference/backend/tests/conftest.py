"""Shared test fixtures.

The `ref` fixture is an INDEPENDENT closed-form Black-76 implementation (SciPy `norm`), written
by hand here so the engine in `oip.quant.black76` is never validated against itself. All units are
RAW (theta per year, vega per 1.0 vol, rho per 1.0 rate) — matching the engine's contract.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from scipy.stats import norm

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class Black76Reference:
    """Hand-written Black-76 on the futures price F. Raw academic units."""

    @staticmethod
    def d1_d2(F: float, K: float, t: float, sigma: float) -> tuple[float, float]:
        srt = sigma * math.sqrt(t)
        d1 = (math.log(F / K) + 0.5 * sigma * sigma * t) / srt
        return d1, d1 - srt

    @classmethod
    def price(cls, flag: str, F: float, K: float, t: float, r: float, sigma: float) -> float:
        d1, d2 = cls.d1_d2(F, K, t, sigma)
        df = math.exp(-r * t)
        if flag == "c":
            return df * (F * norm.cdf(d1) - K * norm.cdf(d2))
        return df * (K * norm.cdf(-d2) - F * norm.cdf(-d1))

    @classmethod
    def delta(cls, flag: str, F: float, K: float, t: float, r: float, sigma: float) -> float:
        d1, _ = cls.d1_d2(F, K, t, sigma)
        df = math.exp(-r * t)
        return df * norm.cdf(d1) if flag == "c" else -df * norm.cdf(-d1)

    @classmethod
    def gamma(cls, flag: str, F: float, K: float, t: float, r: float, sigma: float) -> float:
        d1, _ = cls.d1_d2(F, K, t, sigma)
        df = math.exp(-r * t)
        return df * norm.pdf(d1) / (F * sigma * math.sqrt(t))

    @classmethod
    def vega(cls, flag: str, F: float, K: float, t: float, r: float, sigma: float) -> float:
        # Raw: option price change per 1.00 (100%) change in vol. Same for call/put.
        d1, _ = cls.d1_d2(F, K, t, sigma)
        df = math.exp(-r * t)
        return df * F * norm.pdf(d1) * math.sqrt(t)

    @classmethod
    def theta(cls, flag: str, F: float, K: float, t: float, r: float, sigma: float) -> float:
        # Raw: calendar theta per YEAR = -dPrice/d(tau). Negative for long options.
        d1, d2 = cls.d1_d2(F, K, t, sigma)
        df = math.exp(-r * t)
        decay = -df * F * norm.pdf(d1) * sigma / (2.0 * math.sqrt(t))
        if flag == "c":
            return decay + r * df * (F * norm.cdf(d1) - K * norm.cdf(d2))
        return decay + r * df * (K * norm.cdf(-d2) - F * norm.cdf(-d1))

    @classmethod
    def rho(cls, flag: str, F: float, K: float, t: float, r: float, sigma: float) -> float:
        # Raw: per 1.0 change in r. Under Black-76, r enters only via the discount factor,
        # so rho == -t * price exactly.
        return -t * cls.price(flag, F, K, t, r, sigma)


@pytest.fixture(scope="session")
def ref() -> Black76Reference:
    return Black76Reference()


@pytest.fixture(scope="session")
def known_values() -> dict:
    return json.loads((FIXTURES_DIR / "black76_known_values.json").read_text())


@pytest.fixture(scope="session")
def broker_fixture() -> dict:
    return json.loads((FIXTURES_DIR / "broker_greeks_nifty.json").read_text())


@pytest.fixture()
def sample_chain():
    """A small in-memory NIFTY chain (3 strikes, call+put each with IV) for storage/pipeline/API."""
    from datetime import date, datetime
    from zoneinfo import ZoneInfo

    from oip.domain.enums import Exchange, FuturePriceSource, OptionType
    from oip.domain.models import ChainRow, OptionChain, OptionQuote

    snap = datetime(2026, 6, 12, 15, 30, tzinfo=ZoneInfo("Asia/Kolkata"))

    def quote(ot: OptionType, last: float, iv: float) -> OptionQuote:
        return OptionQuote(
            option_type=ot, last_price=last, bid=last - 0.5, ask=last + 0.5,
            oi=100000, volume=5000, iv_source=iv,
        )

    rows = [
        ChainRow(strike=21900.0, expiry=date(2026, 6, 26),
                 call=quote(OptionType.CALL, 300.0, 0.135), put=quote(OptionType.PUT, 180.0, 0.140)),
        ChainRow(strike=22000.0, expiry=date(2026, 6, 26),
                 call=quote(OptionType.CALL, 250.0, 0.124), put=quote(OptionType.PUT, 235.0, 0.127)),
        ChainRow(strike=22100.0, expiry=date(2026, 6, 26),
                 call=quote(OptionType.CALL, 205.0, 0.122), put=quote(OptionType.PUT, 290.0, 0.130)),
    ]
    return OptionChain(
        underlying="NIFTY", exchange=Exchange.NSE, spot=21987.65, future_price=22014.5,
        future_price_source=FuturePriceSource.NSE_FUTURES, snapshot_ts=snap,
        risk_free_rate=0.065, rows=rows,
    )


@pytest.fixture()
def wide_chain():
    """A 9-strike NIFTY chain (smooth IV smile, realistic OI) for GEX / RND / max-pain tests."""
    from datetime import date, datetime
    from zoneinfo import ZoneInfo

    from oip.domain.enums import Exchange, FuturePriceSource, OptionType
    from oip.domain.models import ChainRow, OptionChain, OptionQuote

    snap = datetime(2026, 6, 12, 15, 30, tzinfo=ZoneInfo("Asia/Kolkata"))
    F = 22000.0
    rows = []
    for k in range(21600, 22401, 100):
        dist = abs(k - 22000) / 100.0
        civ = 0.12 + 0.003 * dist          # smile: wings richer
        piv = civ + 0.004                  # put skew
        # OI: call resistance peaks above, put support peaks below.
        call_oi = 1_000_000 + max(0.0, 6 - abs(k - 22200) / 100.0) * 500_000
        put_oi = 1_000_000 + max(0.0, 6 - abs(k - 21800) / 100.0) * 500_000
        rows.append(
            ChainRow(
                strike=float(k), expiry=date(2026, 6, 26),
                call=OptionQuote(option_type=OptionType.CALL, oi=call_oi, volume=10000, iv_source=civ),
                put=OptionQuote(option_type=OptionType.PUT, oi=put_oi, volume=10000, iv_source=piv),
            )
        )
    return OptionChain(
        underlying="NIFTY", exchange=Exchange.NSE, spot=21980.0, future_price=F,
        future_price_source=FuturePriceSource.NSE_FUTURES, snapshot_ts=snap,
        risk_free_rate=0.065, rows=rows,
    )


@pytest.fixture()
def tmp_settings(tmp_path, monkeypatch):
    """Point config at an isolated temp data dir and clear the cached Settings."""
    from oip.config import get_settings

    monkeypatch.setenv("OIP_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    settings = get_settings()
    (settings.fixtures_dir).mkdir(parents=True, exist_ok=True)
    yield settings
    get_settings.cache_clear()
