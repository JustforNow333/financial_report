from __future__ import annotations

from datetime import datetime, timezone
from datetime import date
from pathlib import Path

from app import create_app
from app.config import Settings
from app.db import get_engine, get_session
from app.models import Base, Company, DailyBar, DailyReturn, PriceDaily, Symbol, Ticker


def _make_settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'test_api.db'}",
        market_data_provider="polygon",
        market_provider="polygon",
        fmp_api_key=None,
        fmp_base_url="https://financialmodelingprep.com",
        eod_ingest_hour_et=18,
        polygon_api_key=None,
        polygon_base_url="https://api.polygon.io",
        request_timeout_seconds=10,
        mover_filter_enabled=True,
        min_last_price=1.0,
        min_day_volume=100_000,
        movers_limit=10,
        ingest_interval_minutes=5,
        industry_llm_enabled=False,
        gemini_api_key=None,
        gemini_base_url="https://generativelanguage.googleapis.com/v1beta",
        gemini_model="gemini-3-flash",
    )


def _seed_daily_data() -> None:
    session = get_session()
    asof_date = date(2026, 2, 13)

    session.add_all(
        [
            Symbol(ticker="AAA", name="AAA Software", exchange="NYSE", industry_label="Software", active=True),
            Symbol(ticker="BBB", name="BBB Bank", exchange="NYSE", industry_label="Banks", active=True),
            Symbol(ticker="CCC", name="CCC Unknown", exchange="NASDAQ", industry_label=None, active=True),
        ]
    )

    session.add_all(
        [
            Company(symbol="AAA", name="AAA Software", industry="Software", exchange="NYSE"),
            Company(symbol="BBB", name="BBB Bank", industry="Banks", exchange="NYSE"),
            Company(symbol="CCC", name="CCC Unknown", industry=None, exchange="NASDAQ"),
        ]
    )

    session.add_all(
        [
            DailyBar(date=asof_date, ticker="AAA", close=10.0, pct_change=0.25, volume=200_000),
            DailyBar(date=asof_date, ticker="BBB", close=9.0, pct_change=-0.10, volume=250_000),
            DailyBar(date=asof_date, ticker="CCC", close=15.0, pct_change=0.50, volume=300_000),
            DailyBar(date=asof_date, ticker="ZZZ", close=5.0, pct_change=0.95, volume=100_000),
        ]
    )

    session.commit()


def test_movers_latest_returns_latest_eod_and_case_insensitive_industry(tmp_path: Path) -> None:
    app = create_app(_make_settings(tmp_path))
    Base.metadata.create_all(get_engine())
    _seed_daily_data()

    client = app.test_client()
    response = client.get("/api/movers/latest?industry=software")
    assert response.status_code == 200

    payload = response.get_json()
    assert payload is not None
    assert payload["industry"] == "software"
    assert payload["asof_date"] == "2026-02-13"
    assert payload["provider"] == "polygon_grouped_daily_bars"
    assert payload["outliers_excluded_count"] == 1
    assert [item["ticker"] for item in payload["gainers"]] == ["AAA"]


def test_movers_latest_returns_404_when_no_snapshots(tmp_path: Path) -> None:
    app = create_app(_make_settings(tmp_path))
    Base.metadata.create_all(get_engine())

    client = app.test_client()
    response = client.get("/api/movers/latest")

    assert response.status_code == 404
    payload = response.get_json()
    assert payload is not None
    assert payload["error"] == "No daily bars available"


def test_api_status_reports_data_readiness(tmp_path: Path) -> None:
    app = create_app(_make_settings(tmp_path))
    Base.metadata.create_all(get_engine())

    client = app.test_client()
    empty_response = client.get("/api/status")
    assert empty_response.status_code == 200

    empty_payload = empty_response.get_json()
    assert empty_payload is not None
    assert empty_payload["status"] == "ok"
    assert empty_payload["has_data"] is False
    assert empty_payload["asof_date"] is None
    assert empty_payload["snapshot_count"] == 0

    session = get_session()
    session.add(
        DailyBar(date=date(2026, 2, 13), ticker="AAA", close=10.0, pct_change=0.25, volume=200_000)
    )
    session.commit()

    data_response = client.get("/api/status")
    assert data_response.status_code == 200
    data_payload = data_response.get_json()
    assert data_payload is not None
    assert data_payload["status"] == "ok"
    assert data_payload["has_data"] is True
    assert data_payload["asof_date"] == "2026-02-13"
    assert data_payload["snapshot_count"] == 1


def test_industries_endpoint_includes_all_and_unlabeled(tmp_path: Path) -> None:
    app = create_app(_make_settings(tmp_path))
    Base.metadata.create_all(get_engine())

    session = get_session()
    session.add_all(
        [
            Symbol(ticker="AAA", name="AAA Software", industry_label="Software", active=True),
            Symbol(ticker="BBB", name="BBB Unknown", industry_label=None, active=True),
        ]
    )
    session.add_all(
        [
            Company(symbol="AAA", name="AAA Software", industry="Software", exchange="NYSE"),
            Company(symbol="BBB", name="BBB Unknown", industry=None, exchange="NYSE"),
        ]
    )
    session.add_all(
        [
            DailyBar(date=date(2026, 2, 13), ticker="AAA", close=10.0, pct_change=0.25, volume=200_000),
            DailyBar(date=date(2026, 2, 13), ticker="BBB", close=5.0, pct_change=-0.10, volume=100_000),
        ]
    )
    session.commit()

    client = app.test_client()
    response = client.get("/api/industries")
    assert response.status_code == 200

    payload = response.get_json()
    assert payload is not None
    assert payload["industries"][0] == "All"
    assert "Software" in payload["industries"]
    assert "Unlabeled" in payload["industries"]


def test_movers_latest_honors_limit_query_param(tmp_path: Path, monkeypatch) -> None:
    app = create_app(_make_settings(tmp_path))
    Base.metadata.create_all(get_engine())

    captured: dict[str, int] = {}

    def _fake_get_latest_movers(
        session,
        *,
        limit: int,
        industry: str | None,
        apply_filters: bool,
        min_last_price: float,
        min_day_volume: int,
    ):
        captured["limit"] = limit
        return date(2026, 2, 13), "All", [], [], 0, 0, "polygon_grouped_daily_bars"

    monkeypatch.setattr("app.routes.get_latest_movers", _fake_get_latest_movers)

    client = app.test_client()
    response = client.get("/api/movers/latest?limit=5")

    assert response.status_code == 200
    assert captured["limit"] == 5


def test_industries_endpoint_includes_ticker_sic_descriptions(tmp_path: Path) -> None:
    app = create_app(_make_settings(tmp_path))
    Base.metadata.create_all(get_engine())

    session = get_session()
    session.add(
        Ticker(
            ticker="AAA",
            company_name="AAA Systems",
            cik=123456,
            exchange="NYSE",
            sic_code=3571,
            sic_description="Electronic Computers",
            updated_at=datetime.now(timezone.utc),
        )
    )
    session.commit()

    client = app.test_client()
    response = client.get("/api/industries")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert "Electronic Computers" in payload["industries"]
