"""Settings, feature flags, and exchange constants.

All settings come from environment variables (see ``.env.example``) so nothing
sensitive is committed. Feature flags gate the execution layer — ``TRADING_AUTOMATION``
must stay OFF until SEBI algo empanelment is in place.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass


def _flag(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _load_env_file() -> None:
    """Load a repo-root ``.env`` into the environment for LOCAL runs (``uvicorn`` / the ``anvil``
    CLI), mirroring what docker-compose's ``env_file: .env`` already does for containers — so the
    same `.env` works everywhere. Real environment variables ALWAYS win (we only ``setdefault``),
    and the test suite is skipped so it always sees clean defaults. Set ``ANVIL_NO_DOTENV=1`` to
    opt out. Must run BEFORE ``Settings`` is defined, since its field defaults read os.environ at
    class-definition time.
    """
    if os.environ.get("ANVIL_NO_DOTENV") or "pytest" in sys.modules or os.environ.get("PYTEST_CURRENT_TEST"):
        return
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")  # repo root
    try:
        with open(path, encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key:
                    os.environ.setdefault(key, val)
    except OSError:
        pass


_load_env_file()


@dataclass(frozen=True)
class Settings:
    # Pricing inputs
    risk_free_rate: float = _float("ANVIL_RISK_FREE_RATE", 0.065)
    dividend_yield: float = _float("ANVIL_DIVIDEND_YIELD", 0.012)

    # Data source
    primary_data_source: str = os.environ.get("ANVIL_PRIMARY_SOURCE", "demo")
    store_path: str = os.environ.get("ANVIL_STORE_PATH", "anvil_store.duckdb")
    ledger_path: str = os.environ.get("ANVIL_LEDGER_PATH", "anvil_ledger.duckdb")
    # Multi-timeframe OHLCV bar store (momentum). SEPARATE DuckDB file so the always-on bar aggregator
    # never contends with the snapshot/ledger single-writer locks.
    bars_path: str = os.environ.get("ANVIL_BARS_PATH", "anvil_bars.duckdb")
    # Persisted meta-label (Innovation I.4) — a small JSON of the trained ACT/ABSTAIN model, refit nightly
    # from resolved history and loaded (cached) on the live/cockpit/API predict path. JSON (not DuckDB) so
    # it never contends with a writer lock and is trivially inspectable.
    meta_label_path: str = os.environ.get("ANVIL_META_LABEL_PATH", "anvil_meta_label.json")

    # --- Wave 0: one-process live cockpit supervisor (anvil go-live) ---
    # When on, the API lifespan starts LiveSupervisor (recorder + cockpit predictions + nightly moat
    # clock) as background tasks IN THE SAME PROCESS, so the cockpit updates live. Default OFF so
    # `anvil serve` stays a plain API; `anvil go-live` flips it on.
    live_supervisor_enabled: bool = _flag("ANVIL_LIVE_SUPERVISOR", False)
    cockpit_underlyings: str = os.environ.get("ANVIL_COCKPIT_UNDERLYINGS", "NIFTY,BANKNIFTY")
    nightly_cycle_ist: str = os.environ.get("ANVIL_NIGHTLY_CYCLE_IST", "15:40")  # HH:MM IST moat clock
    recorder_cadence_s: int = _int("ANVIL_RECORDER_CADENCE_S", 60)
    cockpit_cadence_s: int = _int("ANVIL_COCKPIT_CADENCE_S", 60)
    cockpit_force_open: bool = _flag("ANVIL_COCKPIT_FORCE_OPEN", False)  # demo cockpit outside hours
    # Single-stock F&O universe (Wave 4) — used only as the FALLBACK floor when no dynamic universe
    # can be screened (no bhavcopy/instrument data). The live engine dynamically SELECTS the universe
    # each cycle (most-liquid + highest-momentum names) — see anvil/tips/universe.py.
    stock_options_universe: str = os.environ.get(
        "ANVIL_STOCK_OPTIONS_UNIVERSE",
        "RELIANCE,HDFCBANK,ICICIBANK,INFY,TCS,SBIN,AXISBANK,KOTAKBANK,ITC,LT")

    # --- Live, chain-driven single-stock tips (the cross-sectional engine; tips/stocks.py) ---
    # When on, /api/tips/equities is computed LIVE: a dynamic universe (liquidity + momentum screen)
    # is deep-analysed through the SAME full pipeline as the index (chain greeks/IV/OI/skew/GEX +
    # multi-timeframe momentum), ranked cross-sectionally. False reverts to the legacy EOD store read.
    stock_tips_live: bool = _flag("ANVIL_STOCK_TIPS_LIVE", True)
    # How many top opportunities to deep-analyse (one live chain call each — keep modest).
    stock_universe_top_n: int = _int("ANVIL_STOCK_UNIVERSE_TOP_N", 15)
    # Size of the cheap stage-1 candidate screen the top_n is chosen from.
    stock_universe_screen_n: int = _int("ANVIL_STOCK_UNIVERSE_SCREEN_N", 40)
    # API cache freshness window (s): a request older than this recomputes; otherwise served warm.
    stock_refresh_ttl_s: int = _int("ANVIL_STOCK_REFRESH_TTL_S", 90)
    # Bounded fan-out parallelism for the per-stock chain fetch (rate-limit guard).
    stock_refresh_concurrency: int = _int("ANVIL_STOCK_REFRESH_CONCURRENCY", 4)
    # When on (in `anvil go-live`), the supervisor warms the stock cache + records tips to the moat.
    stock_cockpit_enabled: bool = _flag("ANVIL_STOCK_COCKPIT", False)
    stock_cockpit_cadence_s: int = _int("ANVIL_STOCK_COCKPIT_CADENCE_S", 180)

    # App database (multi-user OLTP: users, sessions, watchlists, alerts, …). Postgres in prod
    # via compose; sqlite+aiosqlite locally so dev/tests need no Docker. DuckDB/Parquet stay the
    # research/calibration moat (store_path/ledger_path above) and are unaffected by this.
    database_url: str = os.environ.get("ANVIL_DATABASE_URL", "sqlite+aiosqlite:///./anvil_app.db")
    # Encrypts broker tokens at rest (Fernet) and signs session material. MUST be set in prod;
    # a missing key disables broker-token persistence rather than storing secrets in the clear.
    secret_key: str | None = os.environ.get("ANVIL_SECRET_KEY") or None
    # Dev mode: enables permissive CORS for the Vite dev server (cross-origin :5173 → :8000).
    dev_mode: bool = _flag("ANVIL_DEV", False)

    # Credentials (presence enables live mode)
    # Upstox OAuth (primary chain/Greeks/IV source)
    upstox_api_key: str | None = os.environ.get("UPSTOX_API_KEY") or None
    upstox_api_secret: str | None = os.environ.get("UPSTOX_API_SECRET") or None
    upstox_redirect_uri: str = os.environ.get("UPSTOX_REDIRECT_URI", "http://127.0.0.1:8765/callback")
    upstox_access_token: str | None = os.environ.get("UPSTOX_ACCESS_TOKEN") or None
    # Dhan (fallback chain)
    dhan_client_id: str | None = os.environ.get("DHAN_CLIENT_ID") or None
    dhan_access_token: str | None = os.environ.get("DHAN_ACCESS_TOKEN") or None
    # Zerodha Kite (positions only)
    kite_api_key: str | None = os.environ.get("KITE_API_KEY") or None
    kite_api_secret: str | None = os.environ.get("KITE_API_SECRET") or None
    kite_access_token: str | None = os.environ.get("KITE_ACCESS_TOKEN") or None
    kite_mcp_url: str = os.environ.get("KITE_MCP_URL", "https://mcp.kite.trade/mcp")
    # Groww (data fallback + execution gateway)
    groww_api_key: str | None = os.environ.get("GROWW_API_KEY") or None
    groww_api_secret: str | None = os.environ.get("GROWW_API_SECRET") or None
    groww_totp_seed: str | None = os.environ.get("GROWW_TOTP_SEED") or None
    # A dashboard-issued / pasted Groww access token (used directly; skips key+TOTP generation).
    groww_access_token: str | None = os.environ.get("GROWW_ACCESS_TOKEN") or None
    groww_mcp_url: str = os.environ.get("GROWW_MCP_URL", "https://mcp.groww.in/mcp")
    # Where daily OAuth tokens are cached
    token_dir: str = os.environ.get("ANVIL_TOKEN_DIR", os.path.expanduser("~/.anvil/tokens"))

    # Feature flags — execution layer
    assisted_execution: bool = _flag("ASSISTED_EXECUTION", True)
    trading_automation: bool = _flag("TRADING_AUTOMATION", False)  # MUST stay off

    # --- Paper-trading simulation subsystem (personal, gated) ---
    # paper_trading gates the whole /api/paper surface + the strategy/realtime engine. This is the
    # research/mock money-making loop; REAL placement still rides the trading_automation rail above
    # (off). Naked short premium is allowed only when paper_seller_mode is on (owner choice).
    paper_trading: bool = _flag("PAPER_TRADING", True)
    paper_seller_mode: bool = _flag("PAPER_SELLER_MODE", True)
    paper_allow_event_risk: bool = _flag("PAPER_ALLOW_EVENT_RISK", False)

    # Short-term tips engine (/api/tips). Flat-free: every feature available to every logged-in user;
    # this flag only enables/disables the whole tip surface. The headline feed is gated on MEASURED
    # out-of-sample, post-cost edge (the validation store), never on assertion.
    tips_enabled: bool = _flag("TIPS_ENABLED", True)

    # --- Phase 4 personal-mode hard wall (ADR 0006) ---
    # OFF by default => the app is a PUBLIC analytics surface (calibrated probabilities, regime reads,
    # RND bands — ADR-0004-clean). Actionable/sized output (legs, targets, ₹ sizing, VaR/CVaR/ruin) is
    # owner-only behind this flag AND a passing Gate-0 (see anvil/gating.py:personal_mode_armed).
    personal_mode: bool = _flag("ANVIL_PERSONAL_MODE", False)
    # Headline gate freshness: a stored validation verdict older than this many days (or stamped by a
    # superseded gate model_version) is treated as stale and demoted to the watchlist by decide_tier.
    gate_max_stale_days: int = _int("ANVIL_GATE_MAX_STALE_DAYS", 30)

    # Paper account + sizing defaults (aggressive profile — see the plan's objective function).
    paper_starting_capital: float = _float("PAPER_STARTING_CAPITAL", 1_000_000.0)
    paper_risk_fraction: float = _float("PAPER_RISK_FRACTION", 0.05)  # <= max-loss fraction / trade
    paper_kelly_fraction: float = _float("PAPER_KELLY_FRACTION", 0.55)  # fractional Kelly
    paper_max_exposure_pct: float = _float("PAPER_MAX_EXPOSURE_PCT", 0.40)  # gross exposure cap
    paper_max_lots_per_underlying: int = _int("PAPER_MAX_LOTS_PER_UNDERLYING", 20)
    paper_max_open_positions: int = _int("PAPER_MAX_OPEN_POSITIONS", 12)
    paper_min_conviction: float = _float("PAPER_MIN_CONVICTION", 0.55)  # below => no-trade
    # Variance risk premium: realized vol typically runs BELOW implied on Indian index options, so
    # the physical (real-world) move is ~this fraction of the market-implied move. Premium sellers
    # earn the gap; buyers pay it. Used to turn risk-neutral probabilities into a tradeable edge.
    paper_vrp_ratio: float = _float("PAPER_VRP_RATIO", 0.85)

    # Risk-governor knobs.
    paper_max_drawdown_pct: float = _float("PAPER_MAX_DRAWDOWN_PCT", 0.15)  # kill-switch
    paper_max_daily_loss_pct: float = _float("PAPER_MAX_DAILY_LOSS_PCT", 0.06)
    paper_min_liquidity_oi: float = _float("PAPER_MIN_LIQUIDITY_OI", 50_000.0)
    paper_max_spread_pct: float = _float("PAPER_MAX_SPREAD_PCT", 0.06)  # max (ask-bid)/mid per leg

    # Cost model — headline knobs; the full India F&O charge schedule lives in anvil/paper/costs.py.
    paper_slippage_bps: float = _float("PAPER_SLIPPAGE_BPS", 5.0)  # half-spread fallback (bps of mid)
    paper_brokerage_per_order: float = _float("PAPER_BROKERAGE_PER_ORDER", 20.0)  # flat ₹/order

    # --- Phase 4 honest-sizing safeguards (strategy/sizing.size_units) ---
    # Each only makes sizing SAFER (smaller). Shrink Kelly's edge by its sampling error; add a CVaR
    # tail cap and a broker-margin feasibility cap as extra binding terms; hard-cap Kelly on the
    # negatively-skewed short-vol family; size naked/equity risk against a z-sigma true tail.
    paper_edge_shrink_z: float = _float("PAPER_EDGE_SHRINK_Z", 1.0)  # SE haircuts on the Kelly edge (0 => off)
    paper_cvar_budget_pct: float = _float("PAPER_CVAR_BUDGET_PCT", 0.08)  # CVaR-cap budget / equity (0 => off)
    paper_cvar_sigma_divisor: float = _float("PAPER_CVAR_SIGMA_DIVISOR", 2.0)  # parametric tail: sigma≈max_loss/divisor
    paper_short_vol_kelly_cap: float = _float("PAPER_SHORT_VOL_KELLY_CAP", 0.10)  # negative-skew Kelly hard cap
    paper_tail_z: float = _float("PAPER_TAIL_Z", 2.06)  # Normal CVaR-95 multiplier for the true tail

    # --- Calibration layer (Phase 2) ---
    # Maps raw scores → calibrated probabilities (isotonic/Platt/identity), fit per source-class on
    # resolved history. Calibration is the honesty rail + sizing precondition; it is DISPLAY/threshold
    # only and never enters the gate's certification (that would be circular) or sizing math.
    calibration_enabled: bool = _flag("ANVIL_CALIBRATION_ENABLED", True)
    calibration_refit_enabled: bool = _flag("ANVIL_CALIBRATION_REFIT", True)  # nightly refit in cycle
    calibration_min_samples: int = _int("ANVIL_CALIBRATION_MIN_SAMPLES", 50)  # below → identity
    calibration_blend_floor_n: int = _int("ANVIL_CALIBRATION_BLEND_FLOOR_N", 200)  # full map at/above
    calibration_accuracy_floor: float = _float("ANVIL_CALIBRATION_ACCURACY_FLOOR", 0.52)
    calibration_n_splits: int = _int("ANVIL_CALIBRATION_N_SPLITS", 5)  # purged walk-forward folds
    calibration_aci_enabled: bool = _flag("ANVIL_CALIBRATION_ACI", False)  # ACI off until live streams

    # De-magicked thresholds (were hard-coded; now config-backed, optionally calibrated). With no
    # fitted map these reproduce the previous constants exactly (byte-identical behavior).
    iv_crush_threshold: float = _float("ANVIL_IV_CRUSH_THRESHOLD", 66.0)  # crush-score act/abstain
    vrp_unfavorable_hi: float = _float("ANVIL_VRP_UNFAVORABLE_HI", 0.62)  # prob_rich ≥ → UNFAVORABLE
    vrp_favorable_lo: float = _float("ANVIL_VRP_FAVORABLE_LO", 0.45)  # prob_rich ≤ → FAVORABLE
    rnd_directional_hi: float = _float("ANVIL_RND_DIRECTIONAL_HI", 0.54)  # P(above) ≥ → bullish
    rnd_directional_lo: float = _float("ANVIL_RND_DIRECTIONAL_LO", 0.46)  # P(above) ≤ → bearish
    equity_edge_prob_cap: float = _float("ANVIL_EQUITY_EDGE_PROB_CAP", 0.62)  # single-name prior cap


SETTINGS = Settings()


# Index lot sizes (contract size). NSE revises these periodically, so treat these
# only as fallbacks — connectors should read the live value from the instrument
# master. Verify before trusting in production.
INDEX_LOT_SIZE: dict[str, int] = {
    "NIFTY": 75,
    "BANKNIFTY": 35,
    "FINNIFTY": 65,
    "MIDCPNIFTY": 140,
    "NIFTYNXT50": 25,
    "SENSEX": 20,
    "BANKEX": 30,
}

# Typical strike spacing per underlying (fallback only).
INDEX_STRIKE_STEP: dict[str, int] = {
    "NIFTY": 50,
    "BANKNIFTY": 100,
    "FINNIFTY": 50,
    "MIDCPNIFTY": 25,
    "SENSEX": 100,
    "BANKEX": 100,
}

SUPPORTED_INDEXES = list(INDEX_LOT_SIZE.keys())


def lot_size(underlying: str, default: int = 1) -> int:
    return INDEX_LOT_SIZE.get(underlying.upper(), default)


def strike_step(underlying: str, default: int = 50) -> int:
    return INDEX_STRIKE_STEP.get(underlying.upper(), default)
