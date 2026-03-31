from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.international import (
    CuratedInternationalCompany,
    ExchangeSymbol,
    FxRateQuote,
    InternationalQuote,
    compute_pct_growth,
    convert_price_to_usd,
    ingest_international_snapshots,
    load_curated_international_companies,
    validate_seeded_international_companies,
)
from app.models import Base, IngestRun, InternationalSnapshot


class _FakeInternationalProvider:
    provider_name = "eodhd"

    def __init__(self) -> None:
        self._exchange_symbols = {
            "LSE": [
                ExchangeSymbol(code="AAA", name="AAA Plc", exchange="LSE"),
            ],
            "PA": [
                ExchangeSymbol(code="BBB", name="BBB SA", exchange="PA"),
            ],
            "NSE": [
                ExchangeSymbol(code="CCC", name="CCC Ltd", exchange="NSE"),
            ],
            "HK": [
                ExchangeSymbol(code="DDD", name="DDD Holdings", exchange="HK"),
            ],
            "AS": [
                ExchangeSymbol(code="SKIP", name="Skip NV", exchange="AS"),
            ],
            "TO": [
                ExchangeSymbol(code="FAIL", name="Fail Corp", exchange="TO"),
            ],
            "XETRA": [
                ExchangeSymbol(code="DB1", name="Deutsche Boerse", exchange="XETRA"),
            ],
        }
        self._quotes = {
            "AAA.LSE": InternationalQuote(
                symbol="AAA.LSE",
                local_price=100.0,
                previous_local_close=80.0,
                as_of_date=date(2026, 3, 20),
                price_timestamp_utc=datetime(2026, 3, 20, 16, 30, tzinfo=timezone.utc),
                market_cap=1_000_000_000.0,
            ),
            "BBB.PA": InternationalQuote(
                symbol="BBB.PA",
                local_price=50.0,
                previous_local_close=None,
                as_of_date=date(2026, 3, 20),
                price_timestamp_utc=datetime(2026, 3, 20, 16, 30, tzinfo=timezone.utc),
                market_cap=None,
            ),
            "CCC.NSE": InternationalQuote(
                symbol="CCC.NSE",
                local_price=200.0,
                previous_local_close=180.0,
                as_of_date=date(2026, 3, 15),
                price_timestamp_utc=datetime(2026, 3, 15, 10, 0, tzinfo=timezone.utc),
                market_cap=None,
            ),
            "DDD.HK": InternationalQuote(
                symbol="DDD.HK",
                local_price=300.0,
                previous_local_close=290.0,
                as_of_date=date(2026, 3, 20),
                price_timestamp_utc=datetime(2026, 3, 20, 9, 0, tzinfo=timezone.utc),
                market_cap=None,
            ),
        }
        self._fx = {
            "GBP": FxRateQuote(currency="GBP", rate_to_usd=1.25, fx_timestamp_utc=datetime(2026, 3, 20, 18, 0, tzinfo=timezone.utc)),
            "EUR": FxRateQuote(currency="EUR", rate_to_usd=1.08, fx_timestamp_utc=datetime(2026, 3, 20, 18, 0, tzinfo=timezone.utc)),
            "INR": FxRateQuote(currency="INR", rate_to_usd=0.012, fx_timestamp_utc=datetime(2026, 3, 20, 18, 0, tzinfo=timezone.utc)),
        }

    def fetch_exchange_symbols(self, exchange: str) -> list[ExchangeSymbol]:
        return self._exchange_symbols.get(exchange, [])

    def fetch_latest_quote(self, symbol: str) -> InternationalQuote | None:
        if symbol == "FAIL.TO":
            raise RuntimeError("provider failure")
        return self._quotes.get(symbol)

    def fetch_fx_rate_to_usd(self, currency: str) -> FxRateQuote | None:
        return self._fx.get(currency)


def _make_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    return SessionLocal()


def _seed_payload() -> dict[str, object]:
    return {
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
            "Germany": {
                "exchange": "XETRA",
                "currency": "EUR",
                "companies": [
                    {"symbol": "BAD.XETRA", "name": "Not In Exchange", "active": True},
                ],
            },
        },
    }


def test_load_curated_international_companies_reads_seed_file_and_repo_seed_has_100() -> None:
    repo_companies = load_curated_international_companies()
    assert len(repo_companies) == 100


def test_load_curated_international_companies_reads_nested_seed_file(tmp_path: Path) -> None:
    universe_path = tmp_path / "international.seed.json"
    universe_path.write_text(json.dumps(_seed_payload()), encoding="utf-8")

    companies = load_curated_international_companies(universe_path)

    assert [company.symbol for company in companies] == ["AAA.LSE", "WRONG.PA", "BAD.XETRA"]
    assert companies[0].country == "United Kingdom"
    assert companies[1].currency == "EUR"


def test_load_curated_international_companies_falls_back_from_legacy_seed_path(tmp_path: Path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    seed_path = data_dir / "international_companies.seed.json"
    seed_path.write_text(json.dumps(_seed_payload()), encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    companies = load_curated_international_companies("data/international_curated_companies.json")

    assert [company.symbol for company in companies] == ["AAA.LSE", "WRONG.PA", "BAD.XETRA"]


def test_validation_corrects_by_name_and_does_not_shrink_silently(tmp_path: Path) -> None:
    universe_path = tmp_path / "international.seed.json"
    universe_path.write_text(json.dumps(_seed_payload()), encoding="utf-8")
    companies = load_curated_international_companies(universe_path)

    report = validate_seeded_international_companies(companies, _FakeInternationalProvider())

    assert report.seeded_count == 3
    assert report.validated_count == 2
    assert report.corrected_symbols == [
        {
            "seed_symbol": "WRONG.PA",
            "resolved_symbol": "BBB.PA",
            "company_name": "BBB SA",
            "exchange": "PA",
        }
    ]
    assert len(report.invalid_issues) == 1
    assert report.invalid_issues[0].seed_symbol == "BAD.XETRA"


def test_validation_sanitizes_provider_error_messages() -> None:
    class _ErroringProvider:
        def fetch_exchange_symbols(self, exchange: str) -> list[ExchangeSymbol]:
            raise RuntimeError("404 Client Error for url: https://example.test?api_token=secret123&fmt=json")

    companies = [
        CuratedInternationalCompany("AAA.LSE", "AAA Plc", "LSE", "United Kingdom", "GBP", True, "AAA.LSE"),
    ]

    report = validate_seeded_international_companies(companies, _ErroringProvider())

    assert report.validated_count == 0
    assert report.invalid_issues[0].reason == (
        "exchange symbol list fetch failed: "
        "404 Client Error for url: https://example.test?api_token=REDACTED&fmt=json"
    )


def test_pct_growth_and_usd_conversion_helpers() -> None:
    assert compute_pct_growth(110.0, 100.0) == 10.0
    assert compute_pct_growth(110.0, None) is None
    assert convert_price_to_usd(100.0, 1.25) == 125.0
    assert convert_price_to_usd(100.0, None) is None


def test_ingest_international_snapshots_tracks_validation_and_partial_failures() -> None:
    session = _make_session()
    provider = _FakeInternationalProvider()
    companies = [
        CuratedInternationalCompany("AAA.LSE", "AAA Plc", "LSE", "United Kingdom", "GBP", True, "AAA.LSE"),
        CuratedInternationalCompany("BBB.PA", "BBB SA", "PA", "France", "EUR", True, "BBB.PA"),
        CuratedInternationalCompany("CCC.NSE", "CCC Ltd", "NSE", "India", "INR", True, "CCC.NSE"),
        CuratedInternationalCompany("DDD.HK", "DDD Holdings", "HK", "Hong Kong", "HKD", True, "DDD.HK"),
        CuratedInternationalCompany("SKIP.AS", "Skip NV", "AS", "Netherlands", "EUR", False, "SKIP.AS"),
        CuratedInternationalCompany("FAIL.TO", "Fail Corp", "TO", "Canada", "CAD", True, "FAIL.TO"),
        CuratedInternationalCompany("BAD.XETRA", "Not In Exchange", "XETRA", "Germany", "EUR", True, "BAD.XETRA"),
    ]

    summary = ingest_international_snapshots(
        session,
        companies=companies,
        provider=provider,
        run_date=date(2026, 3, 20),
        stale_after_days=3,
    )
    session.commit()

    assert summary["seeded_companies"] == 7
    assert summary["validated_companies"] == 6
    assert summary["successfully_ingested_companies"] == 4
    assert summary["inactive_companies"] == 1
    assert summary["invalid_symbol_count"] == 1
    assert summary["invalid_symbols"][0]["seed_symbol"] == "BAD.XETRA"
    assert summary["failed_fetch_count"] == 1
    assert summary["failed_fetches"][0]["symbol"] == "FAIL.TO"
    assert summary["missing_fx_count"] == 1
    assert summary["missing_fx_symbols"] == ["DDD.HK"]
    assert summary["stale_count"] == 1
    assert summary["stale_symbols"] == ["CCC.NSE"]

    rows = session.execute(select(InternationalSnapshot)).scalars().all()
    assert len(rows) == 4
    by_symbol = {row.provider_symbol: row for row in rows}
    assert by_symbol["AAA.LSE"].usd_price == 125.0
    assert by_symbol["BBB.PA"].market_status == "missing_prev_close"
    assert by_symbol["DDD.HK"].market_status == "missing_fx"

    ingest_run = session.execute(select(IngestRun)).scalar_one()
    assert ingest_run.provider == "eodhd_international"
