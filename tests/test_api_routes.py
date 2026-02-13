from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app import create_app
from app.config import Settings
from app.db import get_engine, get_session
from app.models import Base, Snapshot, Symbol


def _make_settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'test_api.db'}",
        market_provider="polygon",
        polygon_api_key=None,
        polygon_base_url="https://api.polygon.io",
        request_timeout_seconds=10,
        mover_filter_enabled=True,
        min_last_price=1.0,
        min_day_volume=100_000,
        movers_limit=10,
        ingest_interval_minutes=5,
        industry_llm_enabled=False,
        openai_api_key=None,
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4o-mini",
    )


def test_movers_latest_returns_utc_asof_ts_and_case_insensitive_industry(tmp_path: Path) -> None:
    app = create_app(_make_settings(tmp_path))
    Base.metadata.create_all(get_engine())

    session = get_session()
    symbol = Symbol(
        ticker="AAA",
        name="AAA Software",
        exchange="NYSE",
        industry_label="Software",
        active=True,
    )
    session.add(symbol)
    session.flush()

    session.add(
        Snapshot(
            asof_ts=datetime(2026, 2, 13, 15, 30, tzinfo=timezone.utc),
            symbol_id=symbol.id,
            last_price=10,
            prev_close=8,
            pct_change=25,
            day_volume=200_000,
        )
    )
    session.commit()

    client = app.test_client()
    response = client.get("/api/movers/latest?industry=software")
    assert response.status_code == 200

    payload = response.get_json()
    assert payload is not None
    assert payload["industry"] == "software"
    assert payload["asof_ts"].endswith("+00:00")
    assert [item["ticker"] for item in payload["gainers"]] == ["AAA"]


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
    session.commit()

    client = app.test_client()
    response = client.get("/api/industries")
    assert response.status_code == 200

    payload = response.get_json()
    assert payload is not None
    assert payload["industries"][0] == "All"
    assert "Software" in payload["industries"]
    assert "Unlabeled" in payload["industries"]
