"""add SIC columns to tickers

Revision ID: 0005_add_sic_columns_to_tickers
Revises: 0004_add_tickers_daily_bars
Create Date: 2026-02-15 03:10:00

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0005_add_sic_columns_to_tickers"
down_revision = "0004_add_tickers_daily_bars"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tickers", sa.Column("sic_code", sa.Integer(), nullable=True))
    op.add_column("tickers", sa.Column("sic_description", sa.String(length=256), nullable=True))


def downgrade() -> None:
    op.drop_column("tickers", "sic_description")
    op.drop_column("tickers", "sic_code")
