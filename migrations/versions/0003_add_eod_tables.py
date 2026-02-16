"""add eod ingest and returns tables

Revision ID: 0003_add_eod_tables
Revises: 0002_add_industry_columns
Create Date: 2026-02-15 00:00:00

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0003_add_eod_tables"
down_revision = "0002_add_industry_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=True),
        sa.Column("industry", sa.String(length=64), nullable=True),
        sa.Column("exchange", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("symbol"),
    )
    op.create_index(op.f("ix_companies_industry"), "companies", ["industry"], unique=False)

    op.create_table(
        "prices_daily",
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("open", sa.Float(), nullable=True),
        sa.Column("high", sa.Float(), nullable=True),
        sa.Column("low", sa.Float(), nullable=True),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("adj_close", sa.Float(), nullable=True),
        sa.Column("volume", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=32), server_default=sa.text("'fmp'"), nullable=False),
        sa.PrimaryKeyConstraint("symbol", "date"),
    )
    op.create_index("ix_prices_daily_date", "prices_daily", ["date"], unique=False)
    op.create_index("ix_prices_daily_symbol", "prices_daily", ["symbol"], unique=False)

    op.create_table(
        "ingest_runs",
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("asof_date", sa.Date(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("raw_rows", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("valid_rows", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("dropped_rows", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("duplicates", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("parse_errors", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("completeness_ratio", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_index("ix_ingest_runs_asof_date", "ingest_runs", ["asof_date"], unique=False)

    op.create_table(
        "ingest_baselines",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )

    op.create_table(
        "daily_returns",
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("prev_date", sa.Date(), nullable=True),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("prev_close", sa.Float(), nullable=True),
        sa.Column("pct_change", sa.Float(), nullable=True),
        sa.Column("is_outlier", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("outlier_reason", sa.String(length=128), nullable=True),
        sa.PrimaryKeyConstraint("symbol", "date"),
    )
    op.create_index("ix_daily_returns_date", "daily_returns", ["date"], unique=False)
    op.create_index("ix_daily_returns_date_pct_change", "daily_returns", ["date", "pct_change"], unique=False)

    # seed companies from existing symbols when present
    op.execute(
        """
        INSERT INTO companies (symbol, name, exchange)
        SELECT ticker, name, exchange FROM symbols
        WHERE ticker IS NOT NULL
        ON CONFLICT(symbol) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_daily_returns_date_pct_change", table_name="daily_returns")
    op.drop_index("ix_daily_returns_date", table_name="daily_returns")
    op.drop_table("daily_returns")

    op.drop_table("ingest_baselines")

    op.drop_index("ix_ingest_runs_asof_date", table_name="ingest_runs")
    op.drop_table("ingest_runs")

    op.drop_index("ix_prices_daily_symbol", table_name="prices_daily")
    op.drop_index("ix_prices_daily_date", table_name="prices_daily")
    op.drop_table("prices_daily")

    op.drop_index(op.f("ix_companies_industry"), table_name="companies")
    op.drop_table("companies")
