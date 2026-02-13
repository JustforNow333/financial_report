from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base, Snapshot, Symbol
from app.routes import get_latest_movers


def _make_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    return SessionLocal()


def _seed_snapshot_data(session: Session) -> datetime:
    latest_ts = datetime(2026, 2, 13, 15, 30, tzinfo=timezone.utc)

    rows = [
        Symbol(ticker="AAA", name="AAA Software", exchange="NYSE", industry_label="Software", active=True),
        Symbol(ticker="BBB", name="BBB Bank", exchange="NYSE", industry_label="Banks", active=True),
        Symbol(ticker="CCC", name="CCC Devices", exchange="NASDAQ", industry_label=None, active=True),
        Symbol(ticker="DDD", name="DDD Penny", exchange="NASDAQ", industry_label="Software", active=True),
        Symbol(ticker="EEE", name="EEE Illiquid", exchange="NASDAQ", industry_label="Software", active=True),
    ]
    session.add_all(rows)
    session.flush()

    snapshots = [
        Snapshot(
            asof_ts=latest_ts,
            symbol_id=rows[0].id,
            last_price=10,
            prev_close=8,
            pct_change=25,
            day_volume=500_000,
        ),
        Snapshot(
            asof_ts=latest_ts,
            symbol_id=rows[1].id,
            last_price=9,
            prev_close=10,
            pct_change=-10,
            day_volume=600_000,
        ),
        Snapshot(
            asof_ts=latest_ts,
            symbol_id=rows[2].id,
            last_price=15,
            prev_close=10,
            pct_change=50,
            day_volume=900_000,
        ),
        Snapshot(
            asof_ts=latest_ts,
            symbol_id=rows[3].id,
            last_price=0.50,
            prev_close=1,
            pct_change=-50,
            day_volume=2_000_000,
        ),
        Snapshot(
            asof_ts=latest_ts,
            symbol_id=rows[4].id,
            last_price=20,
            prev_close=10,
            pct_change=100,
            day_volume=50_000,
        ),
    ]
    session.add_all(snapshots)
    session.commit()
    return latest_ts


def test_latest_movers_apply_min_price_and_volume_filters() -> None:
    session = _make_session()
    latest_ts = _seed_snapshot_data(session)

    asof_ts, industry, gainers, losers = get_latest_movers(
        session,
        limit=10,
        industry=None,
        apply_filters=True,
        min_last_price=1.0,
        min_day_volume=100_000,
    )

    assert asof_ts is not None
    if asof_ts.tzinfo is None:
        asof_ts = asof_ts.replace(tzinfo=timezone.utc)

    assert asof_ts == latest_ts
    assert industry == "All"
    gainers_tickers = [row["ticker"] for row in gainers]
    losers_tickers = [row["ticker"] for row in losers]
    assert gainers_tickers[:2] == ["CCC", "AAA"]
    assert losers_tickers[:2] == ["BBB", "AAA"]
    assert "DDD" not in gainers_tickers
    assert "EEE" not in gainers_tickers


def test_latest_movers_filter_by_industry_and_unlabeled() -> None:
    session = _make_session()
    _seed_snapshot_data(session)

    _, software_industry, software_gainers, software_losers = get_latest_movers(
        session,
        limit=10,
        industry="Software",
        apply_filters=True,
        min_last_price=1.0,
        min_day_volume=100_000,
    )
    assert software_industry == "Software"
    assert [row["ticker"] for row in software_gainers] == ["AAA"]
    assert [row["ticker"] for row in software_losers] == ["AAA"]

    _, unlabeled_industry, unlabeled_gainers, unlabeled_losers = get_latest_movers(
        session,
        limit=10,
        industry="Unlabeled",
        apply_filters=True,
        min_last_price=1.0,
        min_day_volume=100_000,
    )
    assert unlabeled_industry == "Unlabeled"
    assert [row["ticker"] for row in unlabeled_gainers] == ["CCC"]
    assert [row["ticker"] for row in unlabeled_losers] == ["CCC"]
