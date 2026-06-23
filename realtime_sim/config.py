"""
Anvil Live (realtime_sim) - configuration.

Everything tunable lives here and is documented inline. Defaults are deliberately
conservative. Nothing here promises returns; these are knobs for an analytics tool.

Read-only market data only. No order is ever placed by any module in this package.
"""
from __future__ import annotations

import os

# --- Universe ---------------------------------------------------------------
# Indices carry full option chains (IV / OI / Greeks) -> the richest signal.
INDICES = ["NIFTY", "BANKNIFTY", "SENSEX"]

# Stock universe: liquid NSE F&O / Nifty-50 names by default. Cash-equity predictions
# use daily + intraday candles; this list is fully configurable (env override below).
STOCKS_DEFAULT = [
    "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS",
    "SBIN", "BHARTIARTL", "ITC", "LT", "AXISBANK",
    "KOTAKBANK", "HINDUNILVR", "BAJFINANCE", "MARUTI", "SUNPHARMA",
    "M&M", "WIPRO", "ONGC", "NTPC", "TATASTEEL",
]


def stock_universe() -> list[str]:
    """Stock list, overridable via ANVIL_RT_STOCKS='RELIANCE,INFY,...'."""
    env = os.environ.get("ANVIL_RT_STOCKS", "").strip()
    if env:
        return [s.strip().upper() for s in env.split(",") if s.strip()]
    return list(STOCKS_DEFAULT)


# --- Horizons (v1 directional tips) -----------------------------------------
HORIZONS = {
    "intraday": {"label": "today_close", "trading_days": 0},
    "next_day": {"label": "next_close", "trading_days": 1},
}
PRIMARY_HORIZON = os.environ.get("ANVIL_RT_HORIZON", "next_day")

# --- v1 prediction thresholds (honest + conservative) -----------------------
CONF_CAP = 0.65
ABSTAIN_BAND = 0.04
MIN_CONF_TO_TIP = 0.52
VRP_RATIO = 0.85

# --- v1 paper P&L model -----------------------------------------------------
PAPER_COST_BPS = 8.0
PAPER_CAPITAL_PER_TIP = 100_000.0

# --- Storage ----------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("ANVIL_RT_DB", os.path.join(_HERE, "tips.db"))
REPORTS_DIR = os.path.join(_HERE, "reports")

# --- Upstox instrument keys for indices -------------------------------------
INDEX_INSTRUMENT_KEYS = {
    "NIFTY": "NSE_INDEX|Nifty 50",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
    "FINNIFTY": "NSE_INDEX|Nifty Fin Service",
    "MIDCPNIFTY": "NSE_INDEX|NIFTY MID SELECT",
    "SENSEX": "BSE_INDEX|SENSEX",
    "BANKEX": "BSE_INDEX|BANKEX",
}

INDEX_TOUCH_STEP = {"NIFTY": 100.0, "BANKNIFTY": 500.0, "SENSEX": 200.0,
                    "FINNIFTY": 100.0, "MIDCPNIFTY": 100.0, "BANKEX": 200.0}

DISCLAIMER = (
    "Anvil Live produces calibrated probabilities and ranges from live market data for "
    "ANALYTICS & EDUCATION only. It is NOT investment advice and makes NO guarantee of "
    "profit. Predictions are uncertain; act at your own risk. Read-only - no orders are "
    "ever placed. Reliability is tracked honestly and shown openly so you can judge for "
    "yourself before trusting any tip."
)

# ============================================================================
# Anvil Live v2 (VRP option-structure layer) config.
# Single canonical block (merged: v2-session intent + constants the v2 pipeline
# needs). Conservative defaults inferred from anvil's PAPER_* + the v2 code's
# intent - CONFIRM before trusting any P&L. Read-only; no order is ever placed.
# ============================================================================
V2_CAPITAL = float(os.environ.get("ANVIL_V2_CAPITAL", 1_000_000))   # paper book capital (INR)
V2_DB_PATH = os.environ.get("ANVIL_RT_V2_DB", os.path.join(_HERE, "tips_v2.db"))

# Lot sizes change periodically - these are 2026 fallbacks only (chain lot wins when present).
V2_LOT_SIZE_FALLBACK = {
    "NIFTY": 75, "BANKNIFTY": 35, "SENSEX": 20, "FINNIFTY": 65,
    "MIDCPNIFTY": 120, "BANKEX": 30,
}

# v2 universe (stocks now carry option chains too - verified live on Upstox).
V2_INDICES = ["NIFTY", "BANKNIFTY", "SENSEX"]
V2_STOCKS_DEFAULT = [
    "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS",
    "SBIN", "BHARTIARTL", "LT", "AXISBANK", "MARUTI",
]


def v2_stocks() -> list[str]:
    env = os.environ.get("ANVIL_RT_STOCKS", "").strip()
    if env:
        return [s.strip().upper() for s in env.split(",") if s.strip()]
    return list(V2_STOCKS_DEFAULT)


# Expiry window for structures (avoid 0-DTE gamma; use the near monthly/weekly).
V2_MIN_DAYS_TO_EXPIRY = 2
V2_MAX_DAYS_TO_EXPIRY = 45

# Gate thresholds (physical-measure POP + net-EV-on-risk to even consider a structure).
V2_MIN_POP = 0.55
V2_MIN_EV_ON_RISK = 0.05
V2_VRP_SELL_RATIO = 0.90          # sell premium only when realized/implied <= this (premium rich)
V2_VRP_BUY_RATIO = 1.10           # buy vol only when realized/implied >= this (vol cheap)

# Sizing (units = min of these binds; short-vol Kelly hard-capped to 0.10 in sizing_v2).
V2_RISK_FRACTION = 0.05
V2_KELLY_FRACTION = 0.50
V2_MAX_EXPOSURE_PCT = 0.40
V2_MAX_LOTS_PER_UNDERLYING = 20
V2_DAILY_DRAWDOWN_KILL = 0.06     # halt new entries if intraday book drawdown exceeds this

# Cost model (mirrors anvil/paper/costs.py headline knobs; full stack in costs_v2.py).
V2_SLIPPAGE_BPS = 5.0
V2_BROKERAGE_PER_ORDER = 20.0

# Edge certification (a (strategy,regime) cell is ACTIONABLE only after clearing these).
V2_EDGE_MIN_SAMPLE = 50           # min resolved trades in the cell (gate doctrine n>=50)
V2_EDGE_MIN_EXPECTANCY = 0.0      # mean net P&L per trade must be > this (i.e. positive)

V2_DISCLAIMER = (
    "Anvil Live v2 ranks option-structure trade IDEAS from live market data to study which "
    "approach earns the most, net of realistic India F&O costs. ANALYTICS & EDUCATION ONLY - "
    "NOT investment advice, NOT a buy/sell/target recommendation, NO guaranteed profit. "
    "Premium-selling carries TAIL RISK: it wins often and small, then can lose big on a gap - "
    "the scorecard tracks max drawdown / worst day / MAE so that risk is never hidden. "
    "Read-only: no order is ever placed. In India, paid securities advice can require SEBI "
    "Research-Analyst registration - keep this in the analytics/education lane."
)
