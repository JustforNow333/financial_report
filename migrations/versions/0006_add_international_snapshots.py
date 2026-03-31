"""add international snapshots

Revision ID: 0006_add_international_snapshots
Revises: 0005_add_sic_columns_to_tickers
Create Date: 2026-03-21 00:30:00

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0006_add_international_snapshots"
down_revision = "0005_add_sic_columns_to_tickers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "international_snapshots",
        sa.Column("provider_symbol", sa.String(length=32), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("company_name", sa.String(length=256), nullable=False),
        sa.Column("exchange", sa.String(length=64), nullable=False),
        sa.Column("country", sa.String(length=64), nullable=False),
        sa.Column("local_currency", sa.String(length=16), nullable=False),
        sa.Column("local_price", sa.Float(), nullable=False),
        sa.Column("usd_price", sa.Float(), nullable=True),
        sa.Column("previous_local_close", sa.Float(), nullable=True),
        sa.Column("pct_growth", sa.Float(), nullable=True),
        sa.Column("market_cap", sa.Float(), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("price_timestamp_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fx_timestamp_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("market_status", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("provider_symbol", "as_of_date"),
    )
    op.create_index(
        "ix_international_snapshots_asof_date",
        "international_snapshots",
        ["as_of_date"],
        unique=False,
    )
    op.create_index(
        "ix_international_snapshots_country",
        "international_snapshots",
        ["country"],
        unique=False,
    )
    op.create_index(
        "ix_international_snapshots_exchange",
        "international_snapshots",
        ["exchange"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_international_snapshots_exchange", table_name="international_snapshots")
    op.drop_index("ix_international_snapshots_country", table_name="international_snapshots")
    op.drop_index("ix_international_snapshots_asof_date", table_name="international_snapshots")
    op.drop_table("international_snapshots")
