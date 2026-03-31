from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models import IngestRun, InternationalSnapshot

DEFAULT_INTERNATIONAL_UNIVERSE_PATH = Path("data/international_companies.seed.json")
LEGACY_INTERNATIONAL_UNIVERSE_PATH = Path("data/international_curated_companies.json")
INTERNATIONAL_INGEST_PROVIDER = "eodhd_international"
_NAME_NORMALIZER = re.compile(r"[^A-Z0-9]+")
_API_TOKEN_RE = re.compile(r"(api_token=)[^&\s]+", re.IGNORECASE)


@dataclass(slots=True, frozen=True)
class CuratedInternationalCompany:
    symbol: str
    company_name: str
    exchange: str
    country: str
    currency: str
    active: bool = True
    seed_symbol: str | None = None
    validation_status: str = "seeded"
    validation_note: str | None = None


@dataclass(slots=True, frozen=True)
class InternationalQuote:
    symbol: str
    local_price: float
    previous_local_close: float | None
    as_of_date: date
    price_timestamp_utc: datetime | None
    market_cap: float | None


@dataclass(slots=True, frozen=True)
class FxRateQuote:
    currency: str
    rate_to_usd: float
    fx_timestamp_utc: datetime | None


@dataclass(slots=True, frozen=True)
class ExchangeSymbol:
    code: str
    name: str
    exchange: str
    currency: str | None = None
    country: str | None = None
    type: str | None = None


@dataclass(slots=True, frozen=True)
class SymbolValidationIssue:
    seed_symbol: str
    company_name: str
    exchange: str
    reason: str
    suggested_symbol: str | None = None


@dataclass(slots=True, frozen=True)
class ValidationReport:
    seeded_count: int
    validated_companies: list[CuratedInternationalCompany]
    invalid_issues: list[SymbolValidationIssue]
    corrected_symbols: list[dict[str, str]]
    exchanges_checked: list[str]

    @property
    def validated_count(self) -> int:
        return len(self.validated_companies)


def _parse_active_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return True
    return str(value).strip().lower() in {"1", "true", "t", "yes", "y", "on"}


def _normalize_exchange(value: object) -> str:
    return str(value or "").strip().upper()


def _normalize_company_name(value: str) -> str:
    text = value.strip().upper().replace("&", " AND ")
    return _NAME_NORMALIZER.sub("", text)


def _canonical_symbol(symbol: str, exchange: str) -> str:
    base = str(symbol).strip().upper()
    if "." in base:
        return base
    return f"{base}.{exchange}"


def _safe_error_message(exc: Exception) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    return _API_TOKEN_RE.sub(r"\1REDACTED", text)


def load_curated_international_companies(
    path: str | Path = DEFAULT_INTERNATIONAL_UNIVERSE_PATH,
) -> list[CuratedInternationalCompany]:
    universe_path = Path(path)
    if (
        not universe_path.exists()
        and universe_path == LEGACY_INTERNATIONAL_UNIVERSE_PATH
        and DEFAULT_INTERNATIONAL_UNIVERSE_PATH.exists()
    ):
        universe_path = DEFAULT_INTERNATIONAL_UNIVERSE_PATH
    with universe_path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)

    if isinstance(payload, list):
        companies: list[CuratedInternationalCompany] = []
        seen_symbols: set[str] = set()
        for item in payload:
            if not isinstance(item, dict):
                raise RuntimeError(f"Invalid international universe row in {universe_path}: {item!r}")

            symbol = str(item.get("symbol") or "").strip().upper()
            company_name = str(item.get("company_name") or item.get("name") or "").strip()
            exchange = str(item.get("exchange") or "").strip()
            country = str(item.get("country") or "").strip()
            currency = str(item.get("currency") or "").strip().upper()
            active = _parse_active_flag(item.get("active", True))

            if not symbol or not company_name or not exchange or not country or not currency:
                raise RuntimeError(f"Missing required field in international universe row: {item!r}")
            if symbol in seen_symbols:
                raise RuntimeError(f"Duplicate symbol in international universe: {symbol}")

            seen_symbols.add(symbol)
            companies.append(
                CuratedInternationalCompany(
                    symbol=symbol,
                    company_name=company_name,
                    exchange=exchange,
                    country=country,
                    currency=currency,
                    active=active,
                    seed_symbol=symbol,
                )
            )
        return companies

    if not isinstance(payload, dict):
        raise RuntimeError(f"Curated international universe must be a JSON object or list: {universe_path}")

    countries = payload.get("countries")
    if not isinstance(countries, dict):
        raise RuntimeError(f"Curated international seed file must contain a countries object: {universe_path}")

    companies: list[CuratedInternationalCompany] = []
    seen_symbols: set[str] = set()
    for country_name, country_payload in countries.items():
        if not isinstance(country_payload, dict):
            raise RuntimeError(f"Invalid country entry in {universe_path}: {country_name!r}")

        exchange = str(country_payload.get("exchange") or "").strip()
        currency = str(country_payload.get("currency") or "").strip().upper()
        rows = country_payload.get("companies")
        if not exchange or not currency or not isinstance(rows, list):
            raise RuntimeError(f"Country entry missing exchange/currency/companies in {universe_path}: {country_name!r}")

        for item in rows:
            if not isinstance(item, dict):
                raise RuntimeError(f"Invalid company row in {universe_path}: {item!r}")

            symbol = str(item.get("symbol") or "").strip().upper()
            company_name = str(item.get("name") or item.get("company_name") or "").strip()
            active = _parse_active_flag(item.get("active", True))

            if not symbol or not company_name:
                raise RuntimeError(f"Missing symbol/name in seed row: {item!r}")
            if symbol in seen_symbols:
                raise RuntimeError(f"Duplicate symbol in international seed file: {symbol}")

            seen_symbols.add(symbol)
            companies.append(
                CuratedInternationalCompany(
                    symbol=symbol,
                    company_name=company_name,
                    exchange=exchange,
                    country=str(country_name).strip(),
                    currency=currency,
                    active=active,
                    seed_symbol=symbol,
                )
            )

    return companies


def validate_seeded_international_companies(
    companies: list[CuratedInternationalCompany],
    provider: Any,
) -> ValidationReport:
    grouped: dict[str, list[CuratedInternationalCompany]] = defaultdict(list)
    for company in companies:
        grouped[_normalize_exchange(company.exchange)].append(company)

    validated: list[CuratedInternationalCompany] = []
    invalid: list[SymbolValidationIssue] = []
    corrected: list[dict[str, str]] = []
    exchanges_checked = sorted(grouped)

    for exchange_code, group in grouped.items():
        try:
            symbols = provider.fetch_exchange_symbols(exchange_code)
        except Exception as exc:
            for company in group:
                invalid.append(
                    SymbolValidationIssue(
                        seed_symbol=company.seed_symbol or company.symbol,
                        company_name=company.company_name,
                        exchange=exchange_code,
                        reason=f"exchange symbol list fetch failed: {_safe_error_message(exc)}",
                    )
                )
            continue

        by_symbol: dict[str, ExchangeSymbol] = {}
        by_name: dict[str, list[ExchangeSymbol]] = defaultdict(list)
        for row in symbols:
            canonical = _canonical_symbol(row.code, exchange_code)
            by_symbol[canonical] = row
            normalized_name = _normalize_company_name(row.name)
            if normalized_name:
                by_name[normalized_name].append(row)

        for company in group:
            canonical_seed_symbol = _canonical_symbol(company.symbol, exchange_code)
            exact_match = by_symbol.get(canonical_seed_symbol)
            if exact_match is not None:
                validated.append(
                    CuratedInternationalCompany(
                        symbol=canonical_seed_symbol,
                        company_name=company.company_name,
                        exchange=exchange_code,
                        country=company.country,
                        currency=company.currency,
                        active=company.active,
                        seed_symbol=company.seed_symbol or company.symbol,
                        validation_status="validated",
                    )
                )
                continue

            normalized_name = _normalize_company_name(company.company_name)
            name_matches = by_name.get(normalized_name, [])
            if len(name_matches) == 1:
                corrected_symbol = _canonical_symbol(name_matches[0].code, exchange_code)
                validated.append(
                    CuratedInternationalCompany(
                        symbol=corrected_symbol,
                        company_name=company.company_name,
                        exchange=exchange_code,
                        country=company.country,
                        currency=company.currency,
                        active=company.active,
                        seed_symbol=company.seed_symbol or company.symbol,
                        validation_status="corrected",
                        validation_note=f"Corrected from {(company.seed_symbol or company.symbol)} to {corrected_symbol}",
                    )
                )
                corrected.append(
                    {
                        "seed_symbol": company.seed_symbol or company.symbol,
                        "resolved_symbol": corrected_symbol,
                        "company_name": company.company_name,
                        "exchange": exchange_code,
                    }
                )
                continue

            invalid.append(
                SymbolValidationIssue(
                    seed_symbol=company.seed_symbol or company.symbol,
                    company_name=company.company_name,
                    exchange=exchange_code,
                    reason="symbol not found in exchange symbol list",
                )
            )

    return ValidationReport(
        seeded_count=len(companies),
        validated_companies=validated,
        invalid_issues=invalid,
        corrected_symbols=corrected,
        exchanges_checked=exchanges_checked,
    )


def compute_pct_growth(local_price: float | None, previous_local_close: float | None) -> float | None:
    if local_price is None or previous_local_close is None or previous_local_close <= 0:
        return None
    return round(((local_price / previous_local_close) - 1.0) * 100.0, 6)


def convert_price_to_usd(local_price: float | None, fx_rate_to_usd: float | None) -> float | None:
    if local_price is None or fx_rate_to_usd is None or fx_rate_to_usd <= 0:
        return None
    return local_price * fx_rate_to_usd


def derive_market_status(
    *,
    as_of_date: date,
    run_date: date,
    stale_after_days: int,
    usd_price: float | None,
    previous_local_close: float | None,
) -> str:
    if usd_price is None:
        return "missing_fx"
    if as_of_date < (run_date - timedelta(days=stale_after_days)):
        return "stale"
    if previous_local_close is None:
        return "missing_prev_close"
    return "fresh"


def get_latest_international_asof_date(session: Session) -> date | None:
    return session.scalar(select(func.max(InternationalSnapshot.as_of_date)))


def get_latest_international_ingest_run(session: Session) -> IngestRun | None:
    return session.execute(
        select(IngestRun)
        .where(IngestRun.provider == INTERNATIONAL_INGEST_PROVIDER)
        .order_by(desc(IngestRun.created_at))
        .limit(1)
    ).scalar_one_or_none()


def parse_international_ingest_notes(run: IngestRun | None) -> dict[str, Any]:
    if run is None or not run.notes:
        return {}
    try:
        payload = json.loads(run.notes)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _upsert_international_snapshots(session: Session, rows: list[dict[str, object]]) -> int:
    if not rows:
        return 0

    bind = session.bind
    if bind is None:
        raise RuntimeError("Session bind is not available")

    dialect = bind.dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        stmt = pg_insert(InternationalSnapshot)
        excluded = stmt.excluded
        stmt = stmt.on_conflict_do_update(
            index_elements=["provider_symbol", "as_of_date"],
            set_={
                "company_name": excluded.company_name,
                "exchange": excluded.exchange,
                "country": excluded.country,
                "local_currency": excluded.local_currency,
                "local_price": excluded.local_price,
                "usd_price": excluded.usd_price,
                "previous_local_close": excluded.previous_local_close,
                "pct_growth": excluded.pct_growth,
                "market_cap": excluded.market_cap,
                "provider": excluded.provider,
                "price_timestamp_utc": excluded.price_timestamp_utc,
                "fx_timestamp_utc": excluded.fx_timestamp_utc,
                "market_status": excluded.market_status,
                "created_at": excluded.created_at,
            },
        )
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        stmt = sqlite_insert(InternationalSnapshot)
        excluded = stmt.excluded
        stmt = stmt.on_conflict_do_update(
            index_elements=["provider_symbol", "as_of_date"],
            set_={
                "company_name": excluded.company_name,
                "exchange": excluded.exchange,
                "country": excluded.country,
                "local_currency": excluded.local_currency,
                "local_price": excluded.local_price,
                "usd_price": excluded.usd_price,
                "previous_local_close": excluded.previous_local_close,
                "pct_growth": excluded.pct_growth,
                "market_cap": excluded.market_cap,
                "provider": excluded.provider,
                "price_timestamp_utc": excluded.price_timestamp_utc,
                "fx_timestamp_utc": excluded.fx_timestamp_utc,
                "market_status": excluded.market_status,
                "created_at": excluded.created_at,
            },
        )
    else:
        raise RuntimeError(f"Unsupported SQL dialect for upsert: {dialect}")

    session.execute(stmt, rows)
    session.expire_all()
    return len(rows)


def _record_international_ingest_run(
    session: Session,
    *,
    run_date: date,
    summary: dict[str, Any],
) -> None:
    completeness_ratio = None
    seeded = int(summary.get("seeded_companies", 0))
    successful = int(summary.get("successfully_ingested_companies", 0))
    if seeded > 0:
        completeness_ratio = successful / seeded

    failed_fetches = summary.get("failed_fetches", [])
    invalid_symbols = summary.get("invalid_symbols", [])
    status = "success"
    if failed_fetches or invalid_symbols:
        status = "partial"
    if successful == 0 and seeded > 0:
        status = "failed"

    session.add(
        IngestRun(
            run_id=f"intl-{uuid4().hex[:24]}",
            asof_date=run_date,
            provider=INTERNATIONAL_INGEST_PROVIDER,
            raw_rows=seeded,
            valid_rows=int(summary.get("validated_companies", 0)),
            dropped_rows=len(invalid_symbols) + int(summary.get("inactive_companies", 0)),
            duplicates=0,
            parse_errors=len(failed_fetches),
            completeness_ratio=completeness_ratio,
            status=status,
            notes=json.dumps(summary, sort_keys=True),
        )
    )


def ingest_international_snapshots(
    session: Session,
    *,
    companies: list[CuratedInternationalCompany],
    provider: Any,
    run_date: date | None = None,
    stale_after_days: int = 3,
) -> dict[str, object]:
    effective_run_date = run_date or datetime.now(timezone.utc).date()
    now_utc = datetime.now(timezone.utc)

    validation = validate_seeded_international_companies(companies, provider)

    fx_cache: dict[str, FxRateQuote | None] = {}
    output_rows: list[dict[str, object]] = []
    success_count = 0
    inactive_count = 0
    stale_symbols: list[str] = []
    missing_fx_symbols: list[str] = []
    failed_fetches: list[dict[str, str]] = []
    missing_prev_close_symbols: list[str] = []
    quote_unavailable_symbols: list[str] = []

    for company in validation.validated_companies:
        if not company.active:
            inactive_count += 1
            continue

        try:
            quote = provider.fetch_latest_quote(company.symbol)
        except Exception as exc:
            failed_fetches.append({"symbol": company.symbol, "reason": _safe_error_message(exc)})
            continue

        if quote is None:
            quote_unavailable_symbols.append(company.symbol)
            continue

        fx_quote: FxRateQuote | None
        if company.currency == "USD":
            fx_quote = FxRateQuote(currency="USD", rate_to_usd=1.0, fx_timestamp_utc=now_utc)
        else:
            if company.currency not in fx_cache:
                try:
                    fx_cache[company.currency] = provider.fetch_fx_rate_to_usd(company.currency)
                except Exception:
                    fx_cache[company.currency] = None
            fx_quote = fx_cache.get(company.currency)

        usd_price = convert_price_to_usd(
            quote.local_price,
            fx_quote.rate_to_usd if fx_quote is not None else None,
        )
        if usd_price is None:
            missing_fx_symbols.append(company.symbol)

        if quote.previous_local_close is None:
            missing_prev_close_symbols.append(company.symbol)

        pct_growth = compute_pct_growth(quote.local_price, quote.previous_local_close)
        market_status = derive_market_status(
            as_of_date=quote.as_of_date,
            run_date=effective_run_date,
            stale_after_days=stale_after_days,
            usd_price=usd_price,
            previous_local_close=quote.previous_local_close,
        )
        if market_status == "stale":
            stale_symbols.append(company.symbol)

        output_rows.append(
            {
                "provider_symbol": company.symbol,
                "as_of_date": quote.as_of_date,
                "company_name": company.company_name,
                "exchange": company.exchange,
                "country": company.country,
                "local_currency": company.currency,
                "local_price": quote.local_price,
                "usd_price": usd_price,
                "previous_local_close": quote.previous_local_close,
                "pct_growth": pct_growth,
                "market_cap": quote.market_cap,
                "provider": getattr(provider, "provider_name", "eodhd"),
                "price_timestamp_utc": quote.price_timestamp_utc,
                "fx_timestamp_utc": fx_quote.fx_timestamp_utc if fx_quote is not None else None,
                "market_status": market_status,
                "created_at": now_utc,
            }
        )
        success_count += 1

    upserted_rows = _upsert_international_snapshots(session, output_rows)
    summary: dict[str, Any] = {
        "run_date": effective_run_date.isoformat(),
        "seeded_companies": validation.seeded_count,
        "validated_companies": validation.validated_count,
        "successfully_ingested_companies": success_count,
        "inactive_companies": inactive_count,
        "invalid_symbol_count": len(validation.invalid_issues),
        "invalid_symbols": [asdict(item) for item in validation.invalid_issues],
        "corrected_symbols": validation.corrected_symbols,
        "exchanges_checked": validation.exchanges_checked,
        "failed_fetch_count": len(failed_fetches),
        "failed_fetches": failed_fetches,
        "missing_fx_count": len(missing_fx_symbols),
        "missing_fx_symbols": sorted(missing_fx_symbols),
        "missing_prev_close_count": len(missing_prev_close_symbols),
        "missing_prev_close_symbols": sorted(missing_prev_close_symbols),
        "quote_unavailable_count": len(quote_unavailable_symbols),
        "quote_unavailable_symbols": sorted(quote_unavailable_symbols),
        "stale_count": len(stale_symbols),
        "stale_symbols": sorted(stale_symbols),
        "upserted_rows": upserted_rows,
    }
    _record_international_ingest_run(session, run_date=effective_run_date, summary=summary)
    return summary
