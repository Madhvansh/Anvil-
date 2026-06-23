"""single-owner partial unique index

Revision ID: 0002_single_owner
Revises: 456b6156babe
Create Date: 2026-06-19
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_single_owner"
down_revision: str | None = "456b6156babe"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # At most one row with role='owner' — prevents a racy second owner bootstrap.
    op.create_index(
        "uq_single_owner",
        "users",
        ["role"],
        unique=True,
        postgresql_where=sa.text("role = 'owner'"),
        sqlite_where=sa.text("role = 'owner'"),
    )


def downgrade() -> None:
    op.drop_index("uq_single_owner", table_name="users")
