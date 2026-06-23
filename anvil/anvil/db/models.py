"""SQLAlchemy ORM models for Anvil's multi-user app/OLTP state.

This is the *product* tier — users, sessions, broker tokens, profile, watchlists,
alerts, portfolio snapshots, the device-facing live-forecast mirror, what-changed
diffs, and the behavioral journal. It is deliberately separate from the quant
engine's Pydantic models (``anvil/models.py``) and from the DuckDB/Parquet research
+ calibration moat (``store/``, ``ledger/``), which stay exactly as they are.

Multi-user-ready by construction: every user-scoped row carries ``user_id``. The
app runs as a single owner today; switching on multi-tenant later needs no schema
change. JSON columns map to JSONB on Postgres (prod) and JSON on SQLite (dev/tests).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Portable JSON across Postgres (prod) and SQLite (dev/tests). These columns are read
# whole rather than queried by key, so plain JSON is enough; if internal-key indexing is
# ever needed, switching a column to Postgres JSONB is a trivial additive migration.
JSONCol = JSON()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    # At most one owner (single-owner product) — enforced at the DB layer, not just by the
    # registration count check, so concurrent registers can't create two owners. Partial unique
    # index works on both Postgres and SQLite.
    __table_args__ = (
        Index("uq_single_owner", "role", unique=True, sqlite_where=text("role = 'owner'"),
              postgresql_where=text("role = 'owner'")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(32), default="owner", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    profile: Mapped[UserProfile | None] = relationship(back_populates="user", uselist=False)


class Session(Base):
    """Server-side, revocable session. ``id`` is the opaque token stored in the cookie."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    user_agent: Mapped[str | None] = mapped_column(String(400))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class BrokerToken(Base):
    """Per-user broker OAuth token, encrypted at rest (Fernet). Replaces the global
    ``~/.anvil/tokens`` dir. ``access_token_enc`` is ciphertext, never plaintext."""

    __tablename__ = "broker_tokens"
    __table_args__ = (UniqueConstraint("user_id", "broker", name="uq_broker_tokens_user_broker"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    broker: Mapped[str] = mapped_column(String(32), nullable=False)
    access_token_enc: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    minted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    meta: Mapped[dict | None] = mapped_column(JSONCol)


class UserProfile(Base):
    __tablename__ = "user_profile"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    explain_mode: Mapped[str] = mapped_column(String(16), default="trader", nullable=False)  # simple|trader|expert
    onboarded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    benchmark: Mapped[str] = mapped_column(String(24), default="NIFTY", nullable=False)
    prefs: Mapped[dict] = mapped_column(JSONCol, default=dict, nullable=False)
    # Monetization seam — all features on for the owner now; gating switches here later.
    feature_flags: Mapped[dict] = mapped_column(JSONCol, default=dict, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    user: Mapped[User] = relationship(back_populates="profile")


class Watchlist(Base):
    __tablename__ = "watchlists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    symbols: Mapped[list] = mapped_column(JSONCol, default=list, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AlertRule(Base):
    __tablename__ = "alert_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    underlying: Mapped[str] = mapped_column(String(24), nullable=False)
    # gex_flip_cross|iv_crush|oi_wall_break|unusual_activity|event_risk|price_band|pcr_threshold
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    params: Mapped[dict] = mapped_column(JSONCol, default=dict, nullable=False)
    channel: Mapped[dict] = mapped_column(JSONCol, default=dict, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    cooldown_s: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AlertEvent(Base):
    __tablename__ = "alert_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("alert_rules.id", ondelete="SET NULL"))
    underlying: Mapped[str] = mapped_column(String(24), nullable=False)
    fired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), default="info", nullable=False)  # info|warn|critical
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONCol, default=dict, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(32), default="demo", nullable=False)
    benchmark: Mapped[str] = mapped_column(String(24), default="NIFTY", nullable=False)
    net_delta: Mapped[float] = mapped_column(Float, default=0.0)
    net_gamma: Mapped[float] = mapped_column(Float, default=0.0)
    net_theta: Mapped[float] = mapped_column(Float, default=0.0)
    net_vega: Mapped[float] = mapped_column(Float, default=0.0)
    bw_delta: Mapped[float] = mapped_column(Float, default=0.0)
    bwd_lots: Mapped[float] = mapped_column(Float, default=0.0)
    payload: Mapped[dict] = mapped_column(JSONCol, default=dict, nullable=False)


class LiveForecast(Base):
    """Device-facing mirror of the DuckDB calibration ledger. ``forecast_id`` is the
    ledger's content-hash id, so the moat (DuckDB) stays source of truth while devices
    read 'today's forecasts' from Postgres without touching the single-writer ledger."""

    __tablename__ = "live_forecasts"
    __table_args__ = (UniqueConstraint("user_id", "forecast_id", name="uq_live_forecasts_user_fid"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    forecast_id: Mapped[str] = mapped_column(String(32), nullable=False)
    underlying: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    created_ts: Mapped[str] = mapped_column(String(40), nullable=False)
    resolve_ts: Mapped[str] = mapped_column(String(40), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    params: Mapped[dict] = mapped_column(JSONCol, default=dict, nullable=False)
    prob: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    event: Mapped[int | None] = mapped_column(Integer)  # 0/1 once resolved


class WhatChanged(Base):
    __tablename__ = "what_changed"
    __table_args__ = (UniqueConstraint("user_id", "underlying", "as_of", name="uq_what_changed_user_underlying_asof"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    underlying: Mapped[str] = mapped_column(String(24), nullable=False)
    as_of: Mapped[str] = mapped_column(String(10), nullable=False)  # ISO date
    prev_snapshot_id: Mapped[str | None] = mapped_column(String(128))
    diff: Mapped[dict] = mapped_column(JSONCol, default=dict, nullable=False)
    provenance: Mapped[dict | None] = mapped_column(JSONCol)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class JournalEntry(Base):
    __tablename__ = "behavioral_journal"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    entry_type: Mapped[str] = mapped_column(String(24), default="note", nullable=False)  # note|trade_review|emotion|bias_flag
    underlying: Mapped[str | None] = mapped_column(String(24))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list | None] = mapped_column(JSONCol)
    linked_snapshot_id: Mapped[str | None] = mapped_column(String(128))
    sentiment: Mapped[str | None] = mapped_column(String(16))


# --- Paper-trading subsystem (gated; personal money-making mock loop) -----------------
# These persist the simulator's state. The deterministic replay + report run on the in-memory
# dataclasses (anvil/paper/state.py) and snapshot into these tables; conviction calibration lives
# in the separate DuckDB ledger under an EXCLUDED `paper` class so it never touches the public moat.


class PaperAccount(Base):
    __tablename__ = "paper_account"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), default="paper", nullable=False)
    base_currency: Mapped[str] = mapped_column(String(8), default="INR", nullable=False)
    starting_capital: Mapped[float] = mapped_column(Float, nullable=False)
    cash: Mapped[float] = mapped_column(Float, nullable=False)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    peak_equity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    day_start_equity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    config: Mapped[dict] = mapped_column(JSONCol, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class PaperRun(Base):
    __tablename__ = "paper_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("paper_account.id", ondelete="CASCADE"), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), default="replay", nullable=False)  # realtime | replay
    status: Mapped[str] = mapped_column(String(16), default="running", nullable=False)  # running|paused|done|error
    underlyings: Mapped[list] = mapped_column(JSONCol, default=list, nullable=False)
    cadence_s: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="demo", nullable=False)
    seed: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replay_from: Mapped[str | None] = mapped_column(String(40))
    replay_to: Mapped[str | None] = mapped_column(String(40))
    params: Mapped[dict] = mapped_column(JSONCol, default=dict, nullable=False)
    stats: Mapped[dict] = mapped_column(JSONCol, default=dict, nullable=False)


class PaperRecommendation(Base):
    __tablename__ = "paper_recommendation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("paper_run.id", ondelete="SET NULL"))
    account_id: Mapped[int | None] = mapped_column(ForeignKey("paper_account.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    underlying: Mapped[str] = mapped_column(String(24), nullable=False)
    strategy: Mapped[str] = mapped_column(String(40), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    action: Mapped[str] = mapped_column(String(16), default="trade", nullable=False)
    edge_prob: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    conviction: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    no_trade_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    max_loss: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    max_profit: Mapped[float | None] = mapped_column(Float)
    entry_debit_credit: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    horizon_days: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    decision: Mapped[dict] = mapped_column(JSONCol, default=dict, nullable=False)  # full candidate.to_dict()
    status: Mapped[str] = mapped_column(String(16), default="open", nullable=False)  # open|executed|dismissed|expired
    ledger_forecast_id: Mapped[str | None] = mapped_column(String(40))


class PaperPositionRow(Base):
    __tablename__ = "paper_position"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("paper_account.id", ondelete="CASCADE"), nullable=False)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("paper_run.id", ondelete="SET NULL"))
    recommendation_id: Mapped[int | None] = mapped_column(ForeignKey("paper_recommendation.id", ondelete="SET NULL"))
    underlying: Mapped[str] = mapped_column(String(24), nullable=False)
    strategy: Mapped[str] = mapped_column(String(40), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="open", nullable=False)  # open|closed
    lot_size: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    units: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    legs: Mapped[list] = mapped_column(JSONCol, default=list, nullable=False)
    entry_value: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    max_loss: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    max_profit: Mapped[float | None] = mapped_column(Float)
    reserved_margin: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    mark_value: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    unrealized_pnl: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    charges_paid: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    greeks: Mapped[dict] = mapped_column(JSONCol, default=dict, nullable=False)
    exit_rules: Mapped[dict] = mapped_column(JSONCol, default=dict, nullable=False)
    conviction: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    edge_prob: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    opened_regime: Mapped[str | None] = mapped_column(String(40))
    close_reason: Mapped[str | None] = mapped_column(String(32))
    ledger_forecast_id: Mapped[str | None] = mapped_column(String(40))


class PaperFill(Base):
    __tablename__ = "paper_fill"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("paper_account.id", ondelete="CASCADE"), nullable=False)
    position_id: Mapped[int | None] = mapped_column(ForeignKey("paper_position.id", ondelete="CASCADE"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    underlying: Mapped[str] = mapped_column(String(24), nullable=False)
    instrument_type: Mapped[str] = mapped_column(String(8), default="CE", nullable=False)
    strike: Mapped[float | None] = mapped_column(Float)
    expiry: Mapped[str | None] = mapped_column(String(40))
    option_type: Mapped[str | None] = mapped_column(String(4))
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    lots: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    fill_price: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    ref_mid: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    slippage: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    charges: Mapped[dict] = mapped_column(JSONCol, default=dict, nullable=False)
    kind: Mapped[str] = mapped_column(String(8), default="open", nullable=False)  # open|close
    status: Mapped[str] = mapped_column(String(24), default="FILLED_SIMULATED", nullable=False)


class PaperEquityPoint(Base):
    __tablename__ = "paper_equity_point"
    __table_args__ = (UniqueConstraint("run_id", "ts", name="uq_paper_equity_run_ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("paper_account.id", ondelete="CASCADE"), nullable=False)
    run_id: Mapped[int] = mapped_column(ForeignKey("paper_run.id", ondelete="CASCADE"), nullable=False, index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    equity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    cash: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    unrealized_pnl: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    gross_exposure: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    net_delta: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    open_positions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    drawdown: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
