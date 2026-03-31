from __future__ import annotations

from pathlib import Path

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import asc, desc, func, select

from app.db import get_session
from app.international import (
    get_latest_international_asof_date,
    get_latest_international_ingest_run,
    load_curated_international_companies,
    parse_international_ingest_notes,
)
from app.models import InternationalSnapshot

international_api_bp = Blueprint("international_api", __name__, url_prefix="/api/international")


def _normalize_filter(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _apply_snapshot_filters(stmt, *, country: str | None, exchange: str | None):
    if country:
        stmt = stmt.where(func.lower(InternationalSnapshot.country) == country.lower())
    if exchange:
        stmt = stmt.where(func.lower(InternationalSnapshot.exchange) == exchange.lower())
    return stmt


def _serialize_snapshot(snapshot: InternationalSnapshot) -> dict[str, object]:
    return {
        "ticker": snapshot.provider_symbol,
        "name": snapshot.company_name,
        "exchange": snapshot.exchange,
        "country": snapshot.country,
        "currency": snapshot.local_currency,
        "local_price": snapshot.local_price,
        "usd_price": snapshot.usd_price,
        "prev_close": snapshot.previous_local_close,
        "pct_growth": snapshot.pct_growth,
        "market_cap": snapshot.market_cap,
        "as_of_date": snapshot.as_of_date.isoformat(),
        "provider": snapshot.provider,
        "price_timestamp_utc": snapshot.price_timestamp_utc.isoformat() if snapshot.price_timestamp_utc else None,
        "fx_timestamp_utc": snapshot.fx_timestamp_utc.isoformat() if snapshot.fx_timestamp_utc else None,
        "market_status": snapshot.market_status,
    }


def _load_seed_companies() -> list:
    universe_path = current_app.config.get("INTERNATIONAL_UNIVERSE_PATH", "")
    if not universe_path:
        raise RuntimeError("International universe path is not configured")
    return load_curated_international_companies(Path(str(universe_path)))


@international_api_bp.get("/status")
def international_status() -> object:
    session = get_session()
    asof_date = get_latest_international_asof_date(session)
    latest_run = get_latest_international_ingest_run(session)
    run_notes = parse_international_ingest_notes(latest_run)

    snapshot_count = 0
    stale_count = 0
    if asof_date is not None:
        snapshot_count = int(
            session.scalar(
                select(func.count()).where(InternationalSnapshot.as_of_date == asof_date)
            )
            or 0
        )
        stale_count = int(
            session.scalar(
                select(func.count()).where(
                    InternationalSnapshot.as_of_date == asof_date,
                    InternationalSnapshot.market_status == "stale",
                )
            )
            or 0
        )

    return jsonify(
        {
            "status": "ok",
            "has_data": asof_date is not None,
            "asof_date": asof_date.isoformat() if asof_date else None,
            "snapshot_count": snapshot_count,
            "stale_count": stale_count,
            "provider": "eodhd",
            "latest_run_at": latest_run.created_at.isoformat() if latest_run else None,
            "seeded_companies": run_notes.get("seeded_companies", 0),
            "validated_companies": run_notes.get("validated_companies", 0),
            "successfully_ingested_companies": run_notes.get("successfully_ingested_companies", 0),
            "invalid_symbol_count": run_notes.get("invalid_symbol_count", 0),
            "invalid_symbols": run_notes.get("invalid_symbols", []),
            "missing_fx_count": run_notes.get("missing_fx_count", 0),
            "missing_fx_symbols": run_notes.get("missing_fx_symbols", []),
            "failed_fetch_count": run_notes.get("failed_fetch_count", 0),
            "failed_fetches": run_notes.get("failed_fetches", []),
            "corrected_symbols": run_notes.get("corrected_symbols", []),
            "quote_unavailable_count": run_notes.get("quote_unavailable_count", 0),
        }
    )


@international_api_bp.get("/snapshots/latest")
def international_snapshots_latest() -> tuple[object, int] | object:
    session = get_session()
    asof_date = get_latest_international_asof_date(session)
    if asof_date is None:
        return jsonify({"error": "No international snapshots available"}), 404

    try:
        limit = int(request.args.get("limit", "100"))
    except ValueError:
        return jsonify({"error": "limit must be an integer"}), 400

    limit = max(1, min(limit, 500))
    country = _normalize_filter(request.args.get("country"))
    exchange = _normalize_filter(request.args.get("exchange"))

    stmt = select(InternationalSnapshot).where(InternationalSnapshot.as_of_date == asof_date)
    stmt = _apply_snapshot_filters(stmt, country=country, exchange=exchange)

    total_available = int(session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)

    rows = session.execute(
        stmt.order_by(
            InternationalSnapshot.pct_growth.is_(None),
            desc(InternationalSnapshot.pct_growth),
            asc(InternationalSnapshot.company_name),
        ).limit(limit)
    ).scalars().all()

    return jsonify(
        {
            "asof_date": asof_date.isoformat(),
            "provider": "eodhd",
            "count": len(rows),
            "total_available": total_available,
            "country": country,
            "exchange": exchange,
            "snapshots": [_serialize_snapshot(row) for row in rows],
        }
    )


@international_api_bp.get("/movers/latest")
def international_movers_latest() -> tuple[object, int] | object:
    session = get_session()
    asof_date = get_latest_international_asof_date(session)
    if asof_date is None:
        return jsonify({"error": "No international snapshots available"}), 404

    try:
        limit = int(request.args.get("limit", "10"))
    except ValueError:
        return jsonify({"error": "limit must be an integer"}), 400

    limit = max(1, min(limit, 100))
    country = _normalize_filter(request.args.get("country"))
    exchange = _normalize_filter(request.args.get("exchange"))

    base_stmt = select(InternationalSnapshot).where(
        InternationalSnapshot.as_of_date == asof_date,
        InternationalSnapshot.pct_growth.is_not(None),
    )
    base_stmt = _apply_snapshot_filters(base_stmt, country=country, exchange=exchange)

    gainers = session.execute(
        base_stmt.order_by(desc(InternationalSnapshot.pct_growth)).limit(limit)
    ).scalars().all()
    losers = session.execute(
        base_stmt.order_by(asc(InternationalSnapshot.pct_growth)).limit(limit)
    ).scalars().all()

    return jsonify(
        {
            "asof_date": asof_date.isoformat(),
            "provider": "eodhd",
            "country": country,
            "exchange": exchange,
            "gainers": [_serialize_snapshot(row) for row in gainers],
            "losers": [_serialize_snapshot(row) for row in losers],
        }
    )


@international_api_bp.get("/companies")
def international_companies() -> tuple[object, int] | object:
    try:
        companies = _load_seed_companies()
    except FileNotFoundError:
        return jsonify({"error": "Curated international universe file not found"}), 500
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 500

    session = get_session()
    latest_run = get_latest_international_ingest_run(session)
    run_notes = parse_international_ingest_notes(latest_run)
    invalid_by_symbol = {
        item["seed_symbol"]: item
        for item in run_notes.get("invalid_symbols", [])
        if isinstance(item, dict) and item.get("seed_symbol")
    }
    corrected_by_symbol = {
        item["seed_symbol"]: item
        for item in run_notes.get("corrected_symbols", [])
        if isinstance(item, dict) and item.get("seed_symbol")
    }

    country = _normalize_filter(request.args.get("country"))
    exchange = _normalize_filter(request.args.get("exchange"))
    include_inactive = str(request.args.get("include_inactive", "false")).strip().lower() in {
        "1",
        "true",
        "t",
        "yes",
        "y",
        "on",
    }

    try:
        limit = int(request.args.get("limit", "500"))
    except ValueError:
        return jsonify({"error": "limit must be an integer"}), 400

    limit = max(1, min(limit, 1000))

    filtered = []
    for company in companies:
        if not include_inactive and not company.active:
            continue
        if country and company.country.lower() != country.lower():
            continue
        if exchange and company.exchange.lower() != exchange.lower():
            continue

        seed_symbol = company.seed_symbol or company.symbol
        validation_status = "seeded"
        resolved_symbol = company.symbol
        validation_note = None

        if seed_symbol in corrected_by_symbol:
            validation_status = "corrected"
            resolved_symbol = corrected_by_symbol[seed_symbol].get("resolved_symbol", resolved_symbol)
            validation_note = f"Corrected to {resolved_symbol}"
        elif seed_symbol in invalid_by_symbol:
            validation_status = "invalid"
            validation_note = invalid_by_symbol[seed_symbol].get("reason")

        filtered.append(
            {
                "ticker": seed_symbol,
                "name": company.company_name,
                "exchange": company.exchange,
                "country": company.country,
                "currency": company.currency,
                "active": company.active,
                "validation_status": validation_status,
                "resolved_symbol": resolved_symbol,
                "validation_note": validation_note,
            }
        )

    filtered = filtered[:limit]

    return jsonify(
        {
            "count": len(filtered),
            "country": country,
            "exchange": exchange,
            "companies": filtered,
        }
    )
