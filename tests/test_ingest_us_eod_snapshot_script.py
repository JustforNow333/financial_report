from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select

import scripts.ingest_us_eod_snapshot as ingest_script
from app.db import get_engine, get_session, init_engine, remove_session
from app.models import Base, DailyBar, Ticker


class _ErrorStocksClient:
    calls: list[str] = []

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def get_grouped_daily_bars(self, day: str, adjusted: bool = True, **kwargs):
        _ErrorStocksClient.calls.append(day)
        return {"status": "ERROR", "error": "Unknown API Key"}

    def close(self) -> None:
        return None


class _EmptyTodayStocksClient:
    calls: list[str] = []

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def get_grouped_daily_bars(self, day: str, adjusted: bool = True, **kwargs):
        _EmptyTodayStocksClient.calls.append(day)
        if len(_EmptyTodayStocksClient.calls) == 1:
            return {"results": []}
        return {"results": [{"T": "AAA", "c": 10.0}]}

    def close(self) -> None:
        return None


def test_ingest_us_eod_snapshot_raises_on_polygon_error(monkeypatch) -> None:
    monkeypatch.setenv("POLYGON_API_KEY", "bad-key")
    monkeypatch.setattr(
        ingest_script,
        "_resolve_sessions",
        lambda as_of_date: (date(2026, 3, 17), date(2026, 3, 16)),
    )
    monkeypatch.setattr(ingest_script, "StocksClient", _ErrorStocksClient)
    monkeypatch.setattr(ingest_script.time, "sleep", lambda _: None)

    _ErrorStocksClient.calls = []

    with pytest.raises(RuntimeError, match="Polygon grouped daily bars request failed: Unknown API Key"):
        ingest_script.ingest_us_eod_snapshot(as_of_date=date(2026, 3, 17))

    assert _ErrorStocksClient.calls == ["2026-03-17", "2026-03-16"]


def test_ingest_us_eod_snapshot_keeps_existing_rows_when_polygon_returns_no_data(
    tmp_path, monkeypatch
) -> None:
    database_path = tmp_path / "ingest_script.db"
    init_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(get_engine())

    session = get_session()
    session.add(
        Ticker(
            ticker="AAA",
            company_name="AAA Corp",
            cik=123456,
            exchange="NYSE",
            updated_at=datetime.now(timezone.utc),
        )
    )
    session.add(
        DailyBar(
            date=date(2026, 3, 17),
            ticker="AAA",
            close=10.0,
            pct_change=0.10,
            volume=1_000,
        )
    )
    session.commit()
    remove_session()

    monkeypatch.setenv("POLYGON_API_KEY", "test-key")
    monkeypatch.setattr(
        ingest_script,
        "_resolve_sessions",
        lambda as_of_date: (date(2026, 3, 17), date(2026, 3, 16)),
    )
    monkeypatch.setattr(ingest_script, "StocksClient", _EmptyTodayStocksClient)
    monkeypatch.setattr(ingest_script.time, "sleep", lambda _: None)

    _EmptyTodayStocksClient.calls = []

    with pytest.raises(RuntimeError, match="returned no rows for as_of_date=2026-03-17"):
        ingest_script.ingest_us_eod_snapshot(as_of_date=date(2026, 3, 17))

    assert _EmptyTodayStocksClient.calls == ["2026-03-17", "2026-03-16"]

    session = get_session()
    stored_row = session.scalar(
        select(DailyBar).where(DailyBar.date == date(2026, 3, 17), DailyBar.ticker == "AAA")
    )
    assert stored_row is not None
    assert stored_row.close == 10.0
    assert stored_row.pct_change == pytest.approx(0.10)
