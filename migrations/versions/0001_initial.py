"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-02-13 00:00:00

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "symbols",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=True),
        sa.Column("exchange", sa.String(length=64), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ticker"),
    )
    op.create_index(op.f("ix_symbols_ticker"), "symbols", ["ticker"], unique=False)

    op.create_table(
        "snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asof_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("symbol_id", sa.Integer(), nullable=False),
        sa.Column("last_price", sa.Float(), nullable=True),
        sa.Column("prev_close", sa.Float(), nullable=True),
        sa.Column("pct_change", sa.Float(), nullable=True),
        sa.Column("day_open", sa.Float(), nullable=True),
        sa.Column("day_high", sa.Float(), nullable=True),
        sa.Column("day_low", sa.Float(), nullable=True),
        sa.Column("day_volume", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["symbol_id"], ["symbols.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol_id", "asof_ts", name="uq_snapshot_symbol_asof"),
    )
    op.create_index(op.f("ix_snapshots_asof_ts"), "snapshots", ["asof_ts"], unique=False)
    op.create_index(op.f("ix_snapshots_pct_change"), "snapshots", ["pct_change"], unique=False)
    op.create_index(op.f("ix_snapshots_symbol_id"), "snapshots", ["symbol_id"], unique=False)
    op.create_index(
        "ix_snapshot_asof_pct_change", "snapshots", ["asof_ts", "pct_change"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_snapshot_asof_pct_change", table_name="snapshots")
    op.drop_index(op.f("ix_snapshots_symbol_id"), table_name="snapshots")
    op.drop_index(op.f("ix_snapshots_pct_change"), table_name="snapshots")
    op.drop_index(op.f("ix_snapshots_asof_ts"), table_name="snapshots")
    op.drop_table("snapshots")
    op.drop_index(op.f("ix_symbols_ticker"), table_name="symbols")
    op.drop_table("symbols")
