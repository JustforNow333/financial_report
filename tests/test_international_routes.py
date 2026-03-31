from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from app import create_app
from app.config import Settings
from app.db import get_engine, get_session
from app.models import Base, IngestRun, InternationalSnapshot


def _make_settings(tmp_path: Path, universe_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'test_international_api.db'}",
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
        eodhd_api_key="test-eodhd-key",
        eodhd_base_url="https://eodhd.com",
        international_universe_path=str(universe_path),
        international_stale_after_days=3,
    )


def _write_seed(universe_path: Path) -> None:
    payload = {
        "version": 1,
        "countries": {
            "United Kingdom": {
                "exchange": "LSE",
                "currency": "GBP",
                "companies": [
                    {"symbol": "AAA.LSE", "name": "AAA Plc", "active": True},
                ],
            },
            "France": {
                "exchange": "PA",
                "currency": "EUR",
                "companies": [
                    {"symbol": "WRONG.PA", "name": "BBB SA", "active": True},
                ],
            },
            "Canada": {
                "exchange": "TO",
                "currency": "CAD",
                "companies": [
                    {"symbol": "BAD.TO", "name": "Bad Corp", "active": True},
                    {"symbol": "CCC.TO", "name": "CCC Corp", "active": False},
                ],
            },
        },
    }
    universe_path.write_text(json.dumps(payload), encoding="utf-8")


def _seed_snapshots_and_run() -> None:
    session = get_session()
    session.add_all(
        [
            InternationalSnapshot(
                provider_symbol="AAA.LSE",
                as_of_date=date(2026, 3, 20),
                company_name="AAA Plc",
                exchange="LSE",
                country="United Kingdom",
                local_currency="GBP",
                local_price=100.0,
                usd_price=125.0,
                previous_local_close=90.0,
                pct_growth=11.111111,
                market_cap=1_000_000_000.0,
                provider="eodhd",
                price_timestamp_utc=datetime(2026, 3, 20, 16, 30, tzinfo=timezone.utc),
                fx_timestamp_utc=datetime(2026, 3, 20, 18, 0, tzinfo=timezone.utc),
                market_status="fresh",
            ),
            InternationalSnapshot(
                provider_symbol="BBB.PA",
                as_of_date=date(2026, 3, 20),
                company_name="BBB SA",
                exchange="PA",
                country="France",
                local_currency="EUR",
                local_price=50.0,
                usd_price=54.0,
                previous_local_close=55.0,
                pct_growth=-9.090909,
                market_cap=None,
                provider="eodhd",
                price_timestamp_utc=datetime(2026, 3, 20, 16, 30, tzinfo=timezone.utc),
                fx_timestamp_utc=datetime(2026, 3, 20, 18, 0, tzinfo=timezone.utc),
                market_status="stale",
            ),
        ]
    )
    session.add(
        IngestRun(
            run_id="intl-test-run",
            asof_date=date(2026, 3, 20),
            provider="eodhd_international",
            raw_rows=4,
            valid_rows=3,
            dropped_rows=1,
            duplicates=0,
            parse_errors=1,
            completeness_ratio=0.5,
            status="partial",
            notes=json.dumps(
                {
                    "seeded_companies": 4,
                    "validated_companies": 3,
                    "successfully_ingested_companies": 2,
                    "invalid_symbol_count": 1,
                    "invalid_symbols": [
                        {
                            "seed_symbol": "BAD.TO",
                            "company_name": "Bad Corp",
                            "exchange": "TO",
                            "reason": "symbol not found in exchange symbol list",
                        }
                    ],
                    "missing_fx_count": 1,
                    "missing_fx_symbols": ["DDD.HK"],
                    "failed_fetch_count": 1,
                    "failed_fetches": [{"symbol": "EEE.TSE", "reason": "provider failure"}],
                    "corrected_symbols": [
                        {
                            "seed_symbol": "WRONG.PA",
                            "resolved_symbol": "BBB.PA",
                            "company_name": "BBB SA",
                            "exchange": "PA",
                        }
                    ],
                    "quote_unavailable_count": 1,
                }
            ),
        )
    )
    session.commit()


def test_international_status_snapshot_and_movers_routes(tmp_path: Path) -> None:
    universe_path = tmp_path / "international.seed.json"
    _write_seed(universe_path)

    app = create_app(_make_settings(tmp_path, universe_path))
    Base.metadata.create_all(get_engine())
    _seed_snapshots_and_run()

    client = app.test_client()

    status_response = client.get("/api/international/status")
    assert status_response.status_code == 200
    status_payload = status_response.get_json()
    assert status_payload is not None
    assert status_payload["has_data"] is True
    assert status_payload["snapshot_count"] == 2
    assert status_payload["stale_count"] == 1
    assert status_payload["seeded_companies"] == 4
    assert status_payload["validated_companies"] == 3
    assert status_payload["successfully_ingested_companies"] == 2
    assert status_payload["invalid_symbol_count"] == 1
    assert status_payload["invalid_symbols"][0]["seed_symbol"] == "BAD.TO"
    assert status_payload["corrected_symbols"][0]["resolved_symbol"] == "BBB.PA"

    latest_response = client.get("/api/international/snapshots/latest?country=France&limit=5")
    assert latest_response.status_code == 200
    latest_payload = latest_response.get_json()
    assert latest_payload is not None
    assert latest_payload["asof_date"] == "2026-03-20"
    assert latest_payload["total_available"] == 1
    assert latest_payload["snapshots"][0]["ticker"] == "BBB.PA"
    assert latest_payload["snapshots"][0]["usd_price"] == 54.0
    assert latest_payload["snapshots"][0]["market_status"] == "stale"

    movers_response = client.get("/api/international/movers/latest?limit=10")
    assert movers_response.status_code == 200
    movers_payload = movers_response.get_json()
    assert movers_payload is not None
    assert [row["ticker"] for row in movers_payload["gainers"]] == ["AAA.LSE", "BBB.PA"]
    assert [row["ticker"] for row in movers_payload["losers"]] == ["BBB.PA", "AAA.LSE"]


def test_international_companies_route_exposes_validation_status(tmp_path: Path) -> None:
    universe_path = tmp_path / "international.seed.json"
    _write_seed(universe_path)

    app = create_app(_make_settings(tmp_path, universe_path))
    Base.metadata.create_all(get_engine())
    _seed_snapshots_and_run()

    client = app.test_client()
    response = client.get("/api/international/companies?include_inactive=true&limit=10")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["count"] == 4

    by_ticker = {row["ticker"]: row for row in payload["companies"]}
    assert by_ticker["AAA.LSE"]["validation_status"] == "seeded"
    assert by_ticker["WRONG.PA"]["validation_status"] == "corrected"
    assert by_ticker["WRONG.PA"]["resolved_symbol"] == "BBB.PA"
    assert by_ticker["BAD.TO"]["validation_status"] == "invalid"
    assert by_ticker["CCC.TO"]["active"] is False
