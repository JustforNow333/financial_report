"""add tickers and daily_bars tables

Revision ID: 0004_add_tickers_daily_bars
Revises: 0003_add_eod_tables
Create Date: 2026-02-15 02:00:00

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0004_add_tickers_daily_bars"
down_revision = "0003_add_eod_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tickers",
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.Column("company_name", sa.String(length=256), nullable=False),
        sa.Column("cik", sa.Integer(), nullable=True),
        sa.Column("exchange", sa.String(length=64), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("ticker"),
    )

    op.create_table(
        "daily_bars",
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("pct_change", sa.Float(), nullable=True),
        sa.Column("volume", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("date", "ticker"),
    )
    op.create_index("ix_daily_bars_date", "daily_bars", ["date"], unique=False)
    op.create_index("ix_daily_bars_ticker", "daily_bars", ["ticker"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_daily_bars_ticker", table_name="daily_bars")
    op.drop_index("ix_daily_bars_date", table_name="daily_bars")
    op.drop_table("daily_bars")
    op.drop_table("tickers")
