from __future__ import annotations

from datetime import date

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import asc, desc, distinct, func, or_, select
from sqlalchemy.orm import Session

from .db import get_session
from .models import Company, DailyBar, Symbol, Ticker

api_bp = Blueprint("api", __name__, url_prefix="/api")


def get_latest_asof_date(session: Session) -> date | None:
    return session.scalar(select(func.max(DailyBar.date)))


def _clean_optional_text(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalized_industry_column(column):
    return func.nullif(func.trim(column), "")


def _mover_industry_expression():
    return func.coalesce(
        _normalized_industry_column(Company.industry),
        _normalized_industry_column(Symbol.industry_label),
        _normalized_industry_column(Ticker.sic_description),
    )


def _serialize_mover_row(
    daily_bar: DailyBar,
    ticker_row: Ticker | None,
    symbol: Symbol | None,
    company: Company | None,
    *,
    rank: int,
) -> dict[str, object]:
    industry_value = None
    if company is not None:
        industry_value = _clean_optional_text(company.industry)
    if industry_value is None and symbol is not None:
        industry_value = _clean_optional_text(symbol.industry_label)
    if industry_value is None and ticker_row is not None:
        industry_value = _clean_optional_text(ticker_row.sic_description)

    ticker_company_name = _clean_optional_text(ticker_row.company_name) if ticker_row else None
    company_name = _clean_optional_text(company.name) if company else None
    symbol_name = _clean_optional_text(symbol.name) if symbol else None

    return {
        "rank": rank,
        "ticker": daily_bar.ticker,
        "name": ticker_company_name or company_name or symbol_name,
        "industry_label": industry_value,
        "last_price": daily_bar.close,
        "prev_close": (
            (daily_bar.close / (1.0 + daily_bar.pct_change))
            if daily_bar.pct_change is not None and (1.0 + daily_bar.pct_change) != 0
            else None
        ),
        "pct_change": (daily_bar.pct_change * 100.0) if daily_bar.pct_change is not None else None,
        "volume": daily_bar.volume,
        "asof_date": daily_bar.date.isoformat(),
        "provider": "polygon_grouped_daily_bars",
        "is_outlier": bool(daily_bar.pct_change is not None and abs(daily_bar.pct_change) > 0.80),
    }


def _apply_mover_quality_filters(
    stmt,
    *,
    apply_filters: bool,
    min_last_price: float,
    min_day_volume: int,
):
    if not apply_filters:
        return stmt

    return stmt.where(
        DailyBar.close.is_not(None),
        DailyBar.close >= min_last_price,
        or_(
            DailyBar.volume.is_(None),
            DailyBar.volume >= min_day_volume,
        ),
    )


def _apply_industry_filter(stmt, industry: str | None):
    if industry is None or not industry.strip() or industry.strip().lower() == "all":
        return stmt, "All"

    normalized = industry.strip()
    industry_expr = _mover_industry_expression()

    if normalized.lower() == "unlabeled":
        return stmt.where(industry_expr.is_(None)), "Unlabeled"

    return stmt.where(func.lower(industry_expr) == normalized.lower()), normalized


def _build_movers_base_stmt(
    *,
    asof_date: date,
    apply_filters: bool,
    min_last_price: float,
    min_day_volume: int,
):
    stmt = (
        select(DailyBar, Ticker, Symbol, Company)
        .outerjoin(Ticker, Ticker.ticker == DailyBar.ticker)
        .outerjoin(Symbol, Symbol.ticker == DailyBar.ticker)
        .outerjoin(Company, Company.symbol == DailyBar.ticker)
        .where(
            DailyBar.date == asof_date,
            DailyBar.pct_change.is_not(None),
            func.abs(DailyBar.pct_change) <= 0.80,
        )
    )
    return _apply_mover_quality_filters(
        stmt,
        apply_filters=apply_filters,
        min_last_price=min_last_price,
        min_day_volume=min_day_volume,
    )


def _mover_filter_settings() -> tuple[bool, float, int]:
    return (
        bool(current_app.config.get("MOVER_FILTER_ENABLED", True)),
        float(current_app.config.get("MIN_LAST_PRICE", 1.0)),
        int(current_app.config.get("MIN_DAY_VOLUME", 100000)),
    )


def get_latest_movers(
    session: Session,
    *,
    limit: int,
    industry: str | None,
    apply_filters: bool,
    min_last_price: float,
    min_day_volume: int,
) -> tuple[date | None, str, list[dict[str, object]], list[dict[str, object]], int, int, str]:
    asof_date = get_latest_asof_date(session)
    if asof_date is None:
        return None, "All", [], [], 0, 0, "polygon_grouped_daily_bars"

    base_stmt = _build_movers_base_stmt(
        asof_date=asof_date,
        apply_filters=apply_filters,
        min_last_price=min_last_price,
        min_day_volume=min_day_volume,
    )

    outliers_excluded_count = int(
        session.scalar(
            select(func.count())
            .select_from(DailyBar)
            .where(DailyBar.date == asof_date, DailyBar.pct_change.is_not(None), func.abs(DailyBar.pct_change) > 0.80)
        )
        or 0
    )

    base_stmt, industry_value = _apply_industry_filter(base_stmt, industry)

    total_symbols_considered = int(
        session.scalar(select(func.count()).select_from(base_stmt.subquery())) or 0
    )

    gainers_rows = session.execute(base_stmt.order_by(desc(DailyBar.pct_change)).limit(limit)).all()
    losers_rows = session.execute(base_stmt.order_by(asc(DailyBar.pct_change)).limit(limit)).all()

    gainers = [
        _serialize_mover_row(daily_bar, ticker_row, symbol, company, rank=i)
        for i, (daily_bar, ticker_row, symbol, company) in enumerate(gainers_rows, start=1)
    ]
    losers = [
        _serialize_mover_row(daily_bar, ticker_row, symbol, company, rank=i)
        for i, (daily_bar, ticker_row, symbol, company) in enumerate(losers_rows, start=1)
    ]

    provider = "polygon_grouped_daily_bars"
    return (
        asof_date,
        industry_value,
        gainers,
        losers,
        total_symbols_considered,
        outliers_excluded_count,
        provider,
    )


def get_latest_snapshots(
    session: Session,
    *,
    limit: int,
    sort: str,
    apply_filters: bool,
    min_last_price: float,
    min_day_volume: int,
) -> tuple[date | None, list[dict[str, object]], str, int]:
    asof_date = get_latest_asof_date(session)
    if asof_date is None:
        return None, [], "polygon_grouped_daily_bars", 0

    order_column = desc(DailyBar.pct_change) if sort == "pct_change_desc" else asc(DailyBar.pct_change)

    stmt = _build_movers_base_stmt(
        asof_date=asof_date,
        apply_filters=apply_filters,
        min_last_price=min_last_price,
        min_day_volume=min_day_volume,
    )

    total_symbols_considered = int(
        session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    )

    rows = session.execute(stmt.order_by(order_column).limit(limit)).all()
    snapshots = [
        _serialize_mover_row(daily_bar, ticker_row, symbol, company, rank=i)
        for i, (daily_bar, ticker_row, symbol, company) in enumerate(rows, start=1)
    ]

    provider = "polygon_grouped_daily_bars"
    return asof_date, snapshots, provider, total_symbols_considered


@api_bp.get("/industries")
def industries() -> object:
    session = get_session()

    labels_set: set[str] = set()
    for column in (Company.industry, Symbol.industry_label, Ticker.sic_description):
        values = session.execute(
            select(distinct(column)).where(column.is_not(None), column != "")
        ).scalars().all()
        labels_set.update(str(value).strip() for value in values if value and str(value).strip())

    labels = sorted(labels_set, key=lambda value: value.lower())

    asof_date = get_latest_asof_date(session)
    unlabeled_count = 0
    if asof_date is not None:
        industry_expr = _mover_industry_expression()
        unlabeled_count = int(
            session.scalar(
                select(func.count())
                .select_from(DailyBar)
                .outerjoin(Ticker, Ticker.ticker == DailyBar.ticker)
                .outerjoin(Symbol, Symbol.ticker == DailyBar.ticker)
                .outerjoin(Company, Company.symbol == DailyBar.ticker)
                .where(DailyBar.date == asof_date, industry_expr.is_(None))
            )
            or 0
        )

    response_labels = ["All", *labels]
    if unlabeled_count > 0:
        response_labels.append("Unlabeled")

    return jsonify({"industries": response_labels})


@api_bp.get("/status")
def api_status() -> object:
    session = get_session()
    asof_date = get_latest_asof_date(session)
    has_data = asof_date is not None

    date_value = None
    snapshot_count = 0
    provider = "polygon"
    if asof_date is not None:
        date_value = asof_date.isoformat()
        snapshot_count = int(
            session.scalar(select(func.count()).where(DailyBar.date == asof_date)) or 0
        )
        provider = "polygon_grouped_daily_bars"

    return jsonify(
        {
            "status": "ok",
            "has_data": has_data,
            "asof_date": date_value,
            "asof_ts": f"{date_value}T00:00:00+00:00" if date_value else None,
            "snapshot_count": snapshot_count,
            "provider": provider,
        }
    )


@api_bp.get("/movers/latest")
def movers_latest() -> tuple[object, int] | object:
    session = get_session()

    try:
        limit = int(request.args.get("limit", str(current_app.config.get("MOVERS_LIMIT", 10))))
    except ValueError:
        return jsonify({"error": "limit must be an integer"}), 400

    limit = max(1, min(limit, 100))
    industry = request.args.get("industry")
    apply_filters, min_last_price, min_day_volume = _mover_filter_settings()

    (
        asof_date,
        industry_value,
        gainers,
        losers,
        total_symbols_considered,
        outliers_excluded_count,
        provider,
    ) = get_latest_movers(
        session,
        limit=limit,
        industry=industry,
        apply_filters=apply_filters,
        min_last_price=min_last_price,
        min_day_volume=min_day_volume,
    )
    if asof_date is None:
        return jsonify({"error": "No daily bars available"}), 404

    return jsonify(
        {
            "asof_date": asof_date.isoformat(),
            "asof_ts": f"{asof_date.isoformat()}T00:00:00+00:00",
            "industry": industry_value,
            "provider": provider,
            "total_symbols_considered": total_symbols_considered,
            "outliers_excluded_count": outliers_excluded_count,
            "gainers": gainers,
            "losers": losers,
        }
    )


@api_bp.get("/snapshots/latest")
def snapshots_latest() -> tuple[object, int] | object:
    session = get_session()

    try:
        limit = int(request.args.get("limit", "50"))
    except ValueError:
        return jsonify({"error": "limit must be an integer"}), 400

    limit = max(1, min(limit, 500))
    sort = request.args.get("sort", "pct_change_desc")
    if sort not in {"pct_change_desc", "pct_change_asc"}:
        return jsonify({"error": "sort must be pct_change_desc or pct_change_asc"}), 400

    apply_filters, min_last_price, min_day_volume = _mover_filter_settings()

    asof_date, snapshots, provider, total_symbols_considered = get_latest_snapshots(
        session,
        limit=limit,
        sort=sort,
        apply_filters=apply_filters,
        min_last_price=min_last_price,
        min_day_volume=min_day_volume,
    )
    if asof_date is None:
        return jsonify({"error": "No daily bars available"}), 404

    return jsonify(
        {
            "asof_date": asof_date.isoformat(),
            "asof_ts": f"{asof_date.isoformat()}T00:00:00+00:00",
            "provider": provider,
            "total_symbols_considered": total_symbols_considered,
            "count": len(snapshots),
            "snapshots": snapshots,
        }
    )


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@api_bp.get("/symbols/search")
def symbols_search() -> object:
    session = get_session()
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"query": query, "results": []})

    escaped = _escape_like(query)
    stmt = (
        select(Symbol)
        .where(
            or_(
                Symbol.ticker.ilike(f"%{escaped}%", escape="\\"),
                Symbol.name.ilike(f"%{escaped}%", escape="\\"),
            )
        )
        .order_by(Symbol.ticker.asc())
        .limit(20)
    )
    rows = session.execute(stmt).scalars().all()

    return jsonify(
        {
            "query": query,
            "results": [
                {
                    "ticker": symbol.ticker,
                    "name": symbol.name,
                    "exchange": symbol.exchange,
                    "industry_label": symbol.industry_label,
                    "active": symbol.active,
                }
                for symbol in rows
            ],
        }
    )
