from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Symbol(Base):
    __tablename__ = "symbols"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), unique=True, nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    exchange: Mapped[str | None] = mapped_column(String(64), nullable=True)
    industry_label: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    industry_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    industry_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    industry_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )

    snapshots: Mapped[list["Snapshot"]] = relationship(back_populates="symbol")


class Snapshot(Base):
    __tablename__ = "snapshots"
    __table_args__ = (
        UniqueConstraint("symbol_id", "asof_ts", name="uq_snapshot_symbol_asof"),
        Index("ix_snapshot_asof_pct_change", "asof_ts", "pct_change"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asof_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    symbol_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("symbols.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    last_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    prev_close: Mapped[float | None] = mapped_column(Float, nullable=True)
    pct_change: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)

    day_open: Mapped[float | None] = mapped_column(Float, nullable=True)
    day_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    day_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    day_volume: Mapped[int | None] = mapped_column(Integer, nullable=True)

    symbol: Mapped[Symbol] = relationship(back_populates="snapshots")
