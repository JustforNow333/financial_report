from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.ingest import compute_pct_change, ingest_us_eod_snapshot
from app.models import Base, DailyReturn, PriceDaily


class _MockCalendar:
    class _Index:
        def __init__(self, dates: list[date]) -> None:
            self._dates = dates

        def to_pydatetime(self):
            from datetime import datetime

            return [datetime(d.year, d.month, d.day) for d in self._dates]

    class _Schedule:
        def __init__(self, dates: list[date]) -> None:
            self.index = _MockCalendar._Index(dates)

    def __init__(self, sessions: list[date]) -> None:
        self._sessions = sessions

    def schedule(self, start_date: str, end_date: str):
        return _MockCalendar._Schedule(self._sessions)


class _MockStocksClient:
    today_rows: list[dict[str, object]] = []
    prev_rows: list[dict[str, object]] = []
    calls: list[str] = []

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def get_grouped_daily_bars(self, day: str, adjusted: bool = True, **kwargs):
        _MockStocksClient.calls.append(day)
        if len(_MockStocksClient.calls) == 1:
            return {"results": _MockStocksClient.today_rows}
        return {"results": _MockStocksClient.prev_rows}

    def close(self) -> None:
        return None


def _make_engine_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    return SessionLocal()


def test_compute_pct_change_normal_case() -> None:
    result = compute_pct_change(close=110.0, prev_close=100.0)
    assert result == pytest.approx(0.10)


def test_compute_pct_change_returns_none_for_invalid_prev_close() -> None:
    assert compute_pct_change(close=10.0, prev_close=0.0) is None
    assert compute_pct_change(close=10.0, prev_close=-1.0) is None
    assert compute_pct_change(close=10.0, prev_close=None) is None


def test_ingest_us_eod_snapshot_upserts_and_counts(monkeypatch) -> None:
    session = _make_engine_session()

    # Wire ingest session + calendar + client to deterministic test doubles.
    monkeypatch.setenv("POLYGON_API_KEY", "test-key")
    monkeypatch.setattr("app.ingest.get_session", lambda: session)
    monkeypatch.setattr("app.ingest.remove_session", lambda: None)
    monkeypatch.setattr("app.ingest.StocksClient", _MockStocksClient)
    monkeypatch.setattr("app.ingest.time.sleep", lambda _: None)
    monkeypatch.setattr(
        "app.ingest.mcal.get_calendar",
        lambda _: _MockCalendar([date(2026, 2, 13), date(2026, 2, 14)]),
    )

    _MockStocksClient.calls = []
    _MockStocksClient.today_rows = [
        {"T": "AAA", "c": 10.0},
        {"T": "BBB", "c": 12.0},
        {"T": "NO_PREV", "c": 5.0},
    ]
    _MockStocksClient.prev_rows = [
        {"T": "AAA", "c": 8.0},
        {"T": "BBB", "c": 12.0},
    ]

    summary = ingest_us_eod_snapshot(as_of_date=date(2026, 2, 14))

    assert _MockStocksClient.calls == ["2026-02-14", "2026-02-13"]
    assert summary["tickers_processed"] == 3
    assert summary["pct_change_computed"] == 2
    assert summary["missing_prev_close"] == 1
    assert summary["rows_ingested"] == 3

    stored = session.execute(
        select(DailyReturn).where(DailyReturn.date == date(2026, 2, 14))
    ).scalars().all()
    by_symbol = {row.symbol: row for row in stored}
    assert by_symbol["AAA"].pct_change == 0.25
    assert by_symbol["AAA"].prev_date == date(2026, 2, 13)
    assert by_symbol["NO_PREV"].pct_change is None

    # Idempotent rerun updates existing rows instead of duplicating.
    _MockStocksClient.calls = []
    _MockStocksClient.today_rows = [{"T": "AAA", "c": 11.0}]
    _MockStocksClient.prev_rows = [{"T": "AAA", "c": 10.0}]
    summary2 = ingest_us_eod_snapshot(as_of_date=date(2026, 2, 14))

    assert summary2["rows_updated"] == 1
    price_row = session.scalar(
        select(PriceDaily).where(PriceDaily.symbol == "AAA", PriceDaily.date == date(2026, 2, 14))
    )
    assert price_row is not None
    assert price_row.close == 11.0
