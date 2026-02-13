from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import asc, desc, distinct, func, or_, select
from sqlalchemy.orm import Session

from .db import get_session
from .models import Snapshot, Symbol

api_bp = Blueprint("api", __name__, url_prefix="/api")


def get_latest_asof_ts(session: Session) -> datetime | None:
    return session.scalar(select(func.max(Snapshot.asof_ts)))


def _as_utc_datetime(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _serialize_snapshot_row(
    snapshot: Snapshot,
    symbol: Symbol,
    *,
    rank: int,
) -> dict[str, object]:
    return {
        "rank": rank,
        "ticker": symbol.ticker,
        "name": symbol.name,
        "industry_label": symbol.industry_label,
        "last_price": snapshot.last_price,
        "prev_close": snapshot.prev_close,
        "pct_change": snapshot.pct_change,
        "volume": snapshot.day_volume,
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
        Snapshot.last_price.is_not(None),
        Snapshot.last_price >= min_last_price,
        Snapshot.day_volume.is_not(None),
        Snapshot.day_volume >= min_day_volume,
    )


def _apply_industry_filter(stmt, industry: str | None):
    if industry is None or not industry.strip() or industry.strip().lower() == "all":
        return stmt, "All"

    normalized = industry.strip()
    if normalized.lower() == "unlabeled":
        return stmt.where(Symbol.industry_label.is_(None)), "Unlabeled"

    return stmt.where(func.lower(Symbol.industry_label) == normalized.lower()), normalized


def get_latest_movers(
    session: Session,
    *,
    limit: int,
    industry: str | None,
    apply_filters: bool,
    min_last_price: float,
    min_day_volume: int,
) -> tuple[datetime | None, str, list[dict[str, object]], list[dict[str, object]]]:
    asof_ts = get_latest_asof_ts(session)
    if asof_ts is None:
        return None, "All", [], []

    base_stmt = (
        select(Snapshot, Symbol)
        .join(Symbol, Symbol.id == Snapshot.symbol_id)
        .where(Snapshot.asof_ts == asof_ts, Snapshot.pct_change.is_not(None))
    )
    base_stmt = _apply_mover_quality_filters(
        base_stmt,
        apply_filters=apply_filters,
        min_last_price=min_last_price,
        min_day_volume=min_day_volume,
    )
    base_stmt, industry_value = _apply_industry_filter(base_stmt, industry)

    gainers_rows = session.execute(
        base_stmt.order_by(desc(Snapshot.pct_change)).limit(limit)
    ).all()
    losers_rows = session.execute(base_stmt.order_by(asc(Snapshot.pct_change)).limit(limit)).all()

    gainers = [
        _serialize_snapshot_row(snapshot, symbol, rank=i)
        for i, (snapshot, symbol) in enumerate(gainers_rows, start=1)
    ]
    losers = [
        _serialize_snapshot_row(snapshot, symbol, rank=i)
        for i, (snapshot, symbol) in enumerate(losers_rows, start=1)
    ]
    return asof_ts, industry_value, gainers, losers


def get_latest_snapshots(
    session: Session,
    *,
    limit: int,
    sort: str,
    apply_filters: bool,
    min_last_price: float,
    min_day_volume: int,
) -> tuple[datetime | None, list[dict[str, object]]]:
    asof_ts = get_latest_asof_ts(session)
    if asof_ts is None:
        return None, []

    order_column = desc(Snapshot.pct_change) if sort == "pct_change_desc" else asc(Snapshot.pct_change)

    stmt = (
        select(Snapshot, Symbol)
        .join(Symbol, Symbol.id == Snapshot.symbol_id)
        .where(Snapshot.asof_ts == asof_ts)
        .order_by(order_column)
        .limit(limit)
    )

    stmt = _apply_mover_quality_filters(
        stmt,
        apply_filters=apply_filters,
        min_last_price=min_last_price,
        min_day_volume=min_day_volume,
    )

    rows = session.execute(stmt).all()
    snapshots = [
        _serialize_snapshot_row(snapshot, symbol, rank=i)
        for i, (snapshot, symbol) in enumerate(rows, start=1)
    ]
    return asof_ts, snapshots


@api_bp.get("/industries")
def industries() -> object:
    session = get_session()

    labels = session.execute(
        select(distinct(Symbol.industry_label))
        .where(Symbol.industry_label.is_not(None), Symbol.industry_label != "")
        .order_by(Symbol.industry_label.asc())
    ).scalars().all()

    unlabeled_count = session.scalar(
        select(func.count(Symbol.id)).where(Symbol.industry_label.is_(None))
    )

    response_labels = ["All", *labels]
    if unlabeled_count and unlabeled_count > 0:
        response_labels.append("Unlabeled")

    return jsonify({"industries": response_labels})


@api_bp.get("/movers/latest")
def movers_latest() -> tuple[object, int] | object:
    session = get_session()

    limit = int(current_app.config.get("MOVERS_LIMIT", 10))
    limit = max(1, min(limit, 100))
    industry = request.args.get("industry")
    apply_filters = bool(current_app.config.get("MOVER_FILTER_ENABLED", True))
    min_last_price = float(current_app.config.get("MIN_LAST_PRICE", 1.0))
    min_day_volume = int(current_app.config.get("MIN_DAY_VOLUME", 100000))

    asof_ts, industry_value, gainers, losers = get_latest_movers(
        session,
        limit=limit,
        industry=industry,
        apply_filters=apply_filters,
        min_last_price=min_last_price,
        min_day_volume=min_day_volume,
    )
    if asof_ts is None:
        return jsonify({"error": "No snapshots available"}), 404

    asof_utc = _as_utc_datetime(asof_ts)
    return jsonify(
        {
            "asof_ts": asof_utc.isoformat(),
            "industry": industry_value,
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

    apply_filters = bool(current_app.config.get("MOVER_FILTER_ENABLED", True))
    min_last_price = float(current_app.config.get("MIN_LAST_PRICE", 1.0))
    min_day_volume = int(current_app.config.get("MIN_DAY_VOLUME", 100000))

    asof_ts, snapshots = get_latest_snapshots(
        session,
        limit=limit,
        sort=sort,
        apply_filters=apply_filters,
        min_last_price=min_last_price,
        min_day_volume=min_day_volume,
    )
    if asof_ts is None:
        return jsonify({"error": "No snapshots available"}), 404

    asof_utc = _as_utc_datetime(asof_ts)
    return jsonify(
        {
            "asof_ts": asof_utc.isoformat(),
            "count": len(snapshots),
            "snapshots": snapshots,
        }
    )


@api_bp.get("/symbols/search")
def symbols_search() -> object:
    session = get_session()
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"query": query, "results": []})

    stmt = (
        select(Symbol)
        .where(
            or_(
                Symbol.ticker.ilike(f"%{query}%"),
                Symbol.name.ilike(f"%{query}%"),
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
