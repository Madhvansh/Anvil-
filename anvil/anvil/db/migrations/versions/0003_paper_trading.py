"""paper-trading subsystem tables

Revision ID: 0003_paper_trading
Revises: 0002_single_owner
Create Date: 2026-06-19
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_paper_trading"
down_revision: str | None = "0002_single_owner"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "paper_account",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("base_currency", sa.String(length=8), nullable=False),
        sa.Column("starting_capital", sa.Float(), nullable=False),
        sa.Column("cash", sa.Float(), nullable=False),
        sa.Column("realized_pnl", sa.Float(), nullable=False),
        sa.Column("peak_equity", sa.Float(), nullable=False),
        sa.Column("day_start_equity", sa.Float(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("paper_account", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_paper_account_user_id"), ["user_id"], unique=False)

    op.create_table(
        "paper_run",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("underlyings", sa.JSON(), nullable=False),
        sa.Column("cadence_s", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replay_from", sa.String(length=40), nullable=True),
        sa.Column("replay_to", sa.String(length=40), nullable=True),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("stats", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["paper_account.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("paper_run", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_paper_run_user_id"), ["user_id"], unique=False)

    op.create_table(
        "paper_recommendation",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("underlying", sa.String(length=24), nullable=False),
        sa.Column("strategy", sa.String(length=40), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("edge_prob", sa.Float(), nullable=False),
        sa.Column("conviction", sa.Float(), nullable=False),
        sa.Column("no_trade_score", sa.Float(), nullable=False),
        sa.Column("max_loss", sa.Float(), nullable=False),
        sa.Column("max_profit", sa.Float(), nullable=True),
        sa.Column("entry_debit_credit", sa.Float(), nullable=False),
        sa.Column("horizon_days", sa.Float(), nullable=False),
        sa.Column("decision", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("ledger_forecast_id", sa.String(length=40), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["paper_account.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["paper_run.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("paper_recommendation", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_paper_recommendation_ts"), ["ts"], unique=False)
        batch_op.create_index(batch_op.f("ix_paper_recommendation_user_id"), ["user_id"], unique=False)

    op.create_table(
        "paper_position",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("recommendation_id", sa.Integer(), nullable=True),
        sa.Column("underlying", sa.String(length=24), nullable=False),
        sa.Column("strategy", sa.String(length=40), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("lot_size", sa.Integer(), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False),
        sa.Column("legs", sa.JSON(), nullable=False),
        sa.Column("entry_value", sa.Float(), nullable=False),
        sa.Column("max_loss", sa.Float(), nullable=False),
        sa.Column("max_profit", sa.Float(), nullable=True),
        sa.Column("reserved_margin", sa.Float(), nullable=False),
        sa.Column("mark_value", sa.Float(), nullable=False),
        sa.Column("unrealized_pnl", sa.Float(), nullable=False),
        sa.Column("realized_pnl", sa.Float(), nullable=False),
        sa.Column("charges_paid", sa.Float(), nullable=False),
        sa.Column("greeks", sa.JSON(), nullable=False),
        sa.Column("exit_rules", sa.JSON(), nullable=False),
        sa.Column("conviction", sa.Float(), nullable=False),
        sa.Column("edge_prob", sa.Float(), nullable=False),
        sa.Column("opened_regime", sa.String(length=40), nullable=True),
        sa.Column("close_reason", sa.String(length=32), nullable=True),
        sa.Column("ledger_forecast_id", sa.String(length=40), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["paper_account.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recommendation_id"], ["paper_recommendation.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["run_id"], ["paper_run.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("paper_position", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_paper_position_opened_at"), ["opened_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_paper_position_user_id"), ["user_id"], unique=False)

    op.create_table(
        "paper_fill",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("position_id", sa.Integer(), nullable=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("underlying", sa.String(length=24), nullable=False),
        sa.Column("instrument_type", sa.String(length=8), nullable=False),
        sa.Column("strike", sa.Float(), nullable=True),
        sa.Column("expiry", sa.String(length=40), nullable=True),
        sa.Column("option_type", sa.String(length=4), nullable=True),
        sa.Column("side", sa.String(length=4), nullable=False),
        sa.Column("lots", sa.Integer(), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("fill_price", sa.Float(), nullable=False),
        sa.Column("ref_mid", sa.Float(), nullable=False),
        sa.Column("slippage", sa.Float(), nullable=False),
        sa.Column("charges", sa.JSON(), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["paper_account.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["position_id"], ["paper_position.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("paper_fill", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_paper_fill_position_id"), ["position_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_paper_fill_user_id"), ["user_id"], unique=False)

    op.create_table(
        "paper_equity_point",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("equity", sa.Float(), nullable=False),
        sa.Column("cash", sa.Float(), nullable=False),
        sa.Column("unrealized_pnl", sa.Float(), nullable=False),
        sa.Column("realized_pnl", sa.Float(), nullable=False),
        sa.Column("gross_exposure", sa.Float(), nullable=False),
        sa.Column("net_delta", sa.Float(), nullable=False),
        sa.Column("open_positions", sa.Integer(), nullable=False),
        sa.Column("drawdown", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["paper_account.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["paper_run.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "ts", name="uq_paper_equity_run_ts"),
    )
    with op.batch_alter_table("paper_equity_point", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_paper_equity_point_run_id"), ["run_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_paper_equity_point_user_id"), ["user_id"], unique=False)


def downgrade() -> None:
    for tbl in ("paper_equity_point", "paper_fill", "paper_position", "paper_recommendation", "paper_run", "paper_account"):
        op.drop_table(tbl)
