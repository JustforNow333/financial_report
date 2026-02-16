from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    BigInteger,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
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
    name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    exchange: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    industry_label: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    industry_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    industry_source: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    industry_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )

    snapshots: Mapped[list["Snapshot"]] = relationship(back_populates="symbol")


class Ticker(Base):
    __tablename__ = "tickers"

    ticker: Mapped[str] = mapped_column(String(16), primary_key=True)
    company_name: Mapped[str] = mapped_column(String(256), nullable=False)
    cik: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    exchange: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    sic_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sic_description: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class Company(Base):
    __tablename__ = "companies"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    industry: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    exchange: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


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

    last_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    prev_close: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pct_change: Mapped[Optional[float]] = mapped_column(Float, nullable=True, index=True)

    day_open: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    day_high: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    day_low: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    day_volume: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    symbol: Mapped[Symbol] = relationship(back_populates="snapshots")


class PriceDaily(Base):
    __tablename__ = "prices_daily"
    __table_args__ = (
        Index("ix_prices_daily_date", "date"),
        Index("ix_prices_daily_symbol", "symbol"),
    )

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    high: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    low: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    adj_close: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    volume: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'fmp'"))


class IngestRun(Base):
    __tablename__ = "ingest_runs"
    __table_args__ = (Index("ix_ingest_runs_asof_date", "asof_date"),)

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    asof_date: Mapped[date] = mapped_column(Date, nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    raw_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    valid_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    dropped_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    duplicates: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    parse_errors: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    completeness_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class IngestBaseline(Base):
    __tablename__ = "ingest_baselines"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class DailyReturn(Base):
    __tablename__ = "daily_returns"
    __table_args__ = (
        Index("ix_daily_returns_date", "date"),
        Index("ix_daily_returns_date_pct_change", "date", "pct_change"),
    )

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    prev_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    prev_close: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pct_change: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_outlier: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    outlier_reason: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)


class DailyBar(Base):
    __tablename__ = "daily_bars"
    __table_args__ = (
        Index("ix_daily_bars_date", "date"),
        Index("ix_daily_bars_ticker", "ticker"),
    )

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), primary_key=True)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    pct_change: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    volume: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
