"""add industry labeling columns

Revision ID: 0002_add_industry_columns
Revises: 0001_initial
Create Date: 2026-02-13 00:30:00

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0002_add_industry_columns"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("symbols", sa.Column("industry_label", sa.String(length=64), nullable=True))
    op.add_column("symbols", sa.Column("industry_confidence", sa.Float(), nullable=True))
    op.add_column("symbols", sa.Column("industry_source", sa.String(length=32), nullable=True))
    op.add_column("symbols", sa.Column("industry_updated_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f("ix_symbols_industry_label"), "symbols", ["industry_label"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_symbols_industry_label"), table_name="symbols")
    op.drop_column("symbols", "industry_updated_at")
    op.drop_column("symbols", "industry_source")
    op.drop_column("symbols", "industry_confidence")
    op.drop_column("symbols", "industry_label")
