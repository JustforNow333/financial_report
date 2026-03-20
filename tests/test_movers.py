from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base, Company, DailyBar, Symbol, Ticker
from app.routes import get_latest_movers


def _make_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    return SessionLocal()


def _seed_daily_data(session: Session) -> date:
    latest_date = date(2026, 2, 13)

    session.add_all(
        [
            Symbol(ticker="AAA", name="AAA Software", exchange="NYSE", industry_label="Software", active=True),
            Symbol(ticker="BBB", name="BBB Bank", exchange="NYSE", industry_label="Banks", active=True),
            Symbol(ticker="CCC", name="CCC Devices", exchange="NASDAQ", industry_label=None, active=True),
            Symbol(ticker="DDD", name="DDD Penny", exchange="NASDAQ", industry_label="Software", active=True),
            Symbol(ticker="EEE", name="EEE Illiquid", exchange="NASDAQ", industry_label="Software", active=True),
        ]
    )
    session.add_all(
        [
            Company(symbol="AAA", name="AAA Software", industry="Software", exchange="NYSE"),
            Company(symbol="BBB", name="BBB Bank", industry="Banks", exchange="NYSE"),
            Company(symbol="CCC", name="CCC Devices", industry=None, exchange="NASDAQ"),
            Company(symbol="DDD", name="DDD Penny", industry="Software", exchange="NASDAQ"),
            Company(symbol="EEE", name="EEE Illiquid", industry="Software", exchange="NASDAQ"),
            Company(symbol="FFF", name="FFF Blank Industry", industry="   ", exchange="NASDAQ"),
        ]
    )
    session.add(
        Symbol(ticker="FFF", name="FFF Blank Industry", exchange="NASDAQ", industry_label="  ", active=True)
    )
    session.add(
        Ticker(
            ticker="FFF",
            company_name="FFF Blank Industry",
            cik=123456,
            exchange="NASDAQ",
            sic_code=1234,
            sic_description=" ",
            updated_at=datetime.now(timezone.utc),
        )
    )

    session.add_all(
        [
            DailyBar(date=latest_date, ticker="AAA", close=10.0, pct_change=0.25, volume=500_000),
            DailyBar(date=latest_date, ticker="BBB", close=9.0, pct_change=-0.10, volume=600_000),
            DailyBar(date=latest_date, ticker="CCC", close=15.0, pct_change=0.50, volume=900_000),
            DailyBar(date=latest_date, ticker="DDD", close=0.5, pct_change=-0.50, volume=2_000_000),
            DailyBar(date=latest_date, ticker="EEE", close=20.0, pct_change=1.0, volume=50_000),
            DailyBar(date=latest_date, ticker="FFF", close=18.0, pct_change=0.05, volume=700_000),
        ]
    )

    session.commit()
    return latest_date


def test_latest_movers_apply_min_price_and_volume_filters() -> None:
    session = _make_session()
    latest_date = _seed_daily_data(session)

    asof_date, industry, gainers, losers, considered, outliers_excluded, provider = get_latest_movers(
        session,
        limit=10,
        industry=None,
        apply_filters=True,
        min_last_price=1.0,
        min_day_volume=100_000,
    )

    assert asof_date == latest_date
    assert industry == "All"
    assert provider == "polygon_grouped_daily_bars"
    assert considered == 4
    assert outliers_excluded == 1
    gainers_tickers = [row["ticker"] for row in gainers]
    losers_tickers = [row["ticker"] for row in losers]
    assert gainers_tickers[:3] == ["CCC", "AAA", "FFF"]
    assert losers_tickers[:3] == ["BBB", "FFF", "AAA"]
    assert "DDD" not in gainers_tickers
    assert "EEE" not in gainers_tickers


def test_latest_movers_filter_by_industry_and_unlabeled() -> None:
    session = _make_session()
    _seed_daily_data(session)

    _, software_industry, software_gainers, software_losers, software_considered, *_ = get_latest_movers(
        session,
        limit=10,
        industry="Software",
        apply_filters=True,
        min_last_price=1.0,
        min_day_volume=100_000,
    )
    assert software_industry == "Software"
    assert software_considered == 1
    assert [row["ticker"] for row in software_gainers] == ["AAA"]
    assert [row["ticker"] for row in software_losers] == ["AAA"]

    _, unlabeled_industry, unlabeled_gainers, unlabeled_losers, unlabeled_considered, *_ = get_latest_movers(
        session,
        limit=10,
        industry="Unlabeled",
        apply_filters=True,
        min_last_price=1.0,
        min_day_volume=100_000,
    )
    assert unlabeled_industry == "Unlabeled"
    assert unlabeled_considered == 2
    assert [row["ticker"] for row in unlabeled_gainers] == ["CCC", "FFF"]
    assert [row["ticker"] for row in unlabeled_losers] == ["FFF", "CCC"]
