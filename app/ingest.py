from __future__ import annotations

import argparse
import logging
import time
from collections.abc import Iterable
from datetime import datetime, timezone

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import get_session, init_engine, remove_session
from app.models import Snapshot, Symbol
from app.providers import get_provider
from app.providers.base import MarketSnapshotProvider, SnapshotQuote

logger = logging.getLogger(__name__)


def compute_pct_change(last_price: float | None, prev_close: float | None) -> float | None:
    if last_price is None or prev_close is None or prev_close <= 0:
        return None
    return ((last_price - prev_close) / prev_close) * 100.0


def _normalize_asof_ts(asof_ts: datetime | None) -> datetime:
    ts = asof_ts or datetime.now(timezone.utc)
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _chunked(items: list[str], size: int = 1000) -> Iterable[list[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _upsert_symbols(session: Session, quotes: list[SnapshotQuote]) -> dict[str, int]:
    tickers = sorted({quote.ticker for quote in quotes if quote.ticker})
    if not tickers:
        return {}

    first_seen: dict[str, SnapshotQuote] = {}
    for quote in quotes:
        if quote.ticker and quote.ticker not in first_seen:
            first_seen[quote.ticker] = quote

    symbol_map: dict[str, int] = {}
    for ticker_chunk in _chunked(tickers):
        existing_symbols = session.execute(
            select(Symbol).where(Symbol.ticker.in_(ticker_chunk))
        ).scalars()
        for symbol in existing_symbols:
            symbol_map[symbol.ticker] = symbol.id
            quote = first_seen.get(symbol.ticker)
            if quote is None:
                continue
            if quote.name and symbol.name != quote.name:
                symbol.name = quote.name
            if quote.exchange and symbol.exchange != quote.exchange:
                symbol.exchange = quote.exchange

    missing_tickers = [ticker for ticker in tickers if ticker not in symbol_map]
    if missing_tickers:
        new_symbols = [
            Symbol(
                ticker=ticker,
                name=first_seen[ticker].name,
                exchange=first_seen[ticker].exchange,
                active=True,
            )
            for ticker in missing_tickers
        ]
        session.bulk_save_objects(new_symbols)
        session.flush()

        symbol_map = {}
        for ticker_chunk in _chunked(tickers):
            refreshed_rows = session.execute(
                select(Symbol.ticker, Symbol.id).where(Symbol.ticker.in_(ticker_chunk))
            ).all()
            symbol_map.update({ticker: symbol_id for ticker, symbol_id in refreshed_rows})

    return symbol_map


def _bulk_insert_snapshots(session: Session, rows: list[dict[str, object]]) -> int:
    if not rows:
        return 0

    bind = session.get_bind()
    if bind is None:
        raise RuntimeError("Session bind is not available")

    dialect = bind.dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        stmt = pg_insert(Snapshot).on_conflict_do_nothing(index_elements=["symbol_id", "asof_ts"])
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        stmt = sqlite_insert(Snapshot).on_conflict_do_nothing(
            index_elements=["symbol_id", "asof_ts"]
        )
    else:
        stmt = insert(Snapshot)

    result = session.execute(stmt, rows)
    if result.rowcount is not None and result.rowcount > 0:
        return result.rowcount
    return 0


def ingest_snapshot(
    asof_ts: datetime | None = None,
    *,
    settings: Settings | None = None,
    provider: MarketSnapshotProvider | None = None,
    session: Session | None = None,
) -> dict[str, object]:
    local_settings = settings or Settings.from_env()
    normalized_asof = _normalize_asof_ts(asof_ts)

    owns_session = session is None
    if session is None:
        session = get_session()

    local_provider = provider or get_provider(local_settings)

    try:
        quotes = local_provider.fetch_snapshot(normalized_asof)
        symbol_map = _upsert_symbols(session, quotes)

        snapshot_rows: list[dict[str, object]] = []
        for quote in quotes:
            symbol_id = symbol_map.get(quote.ticker)
            if symbol_id is None:
                continue

            snapshot_rows.append(
                {
                    "asof_ts": normalized_asof,
                    "symbol_id": symbol_id,
                    "last_price": quote.last_price,
                    "prev_close": quote.prev_close,
                    "pct_change": compute_pct_change(quote.last_price, quote.prev_close),
                    "day_open": quote.day_open,
                    "day_high": quote.day_high,
                    "day_low": quote.day_low,
                    "day_volume": quote.day_volume,
                }
            )

        inserted_snapshots = _bulk_insert_snapshots(session, snapshot_rows)

        if owns_session:
            session.commit()

        summary = {
            "asof_ts": normalized_asof.isoformat(),
            "fetched_count": len(quotes),
            "prepared_snapshots": len(snapshot_rows),
            "inserted_snapshots": inserted_snapshots,
            "symbols_in_snapshot": len(symbol_map),
        }
        logger.info("Snapshot ingest complete: %s", summary)
        return summary
    except Exception:
        session.rollback()
        logger.exception("Snapshot ingest failed")
        raise
    finally:
        if owns_session:
            remove_session()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest market snapshot data")
    parser.add_argument("--once", action="store_true", help="Run ingestion once and exit")
    parser.add_argument(
        "--interval-minutes",
        type=int,
        default=None,
        help="Run ingestion in a loop every N minutes",
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = _parse_args()

    settings = Settings.from_env()
    init_engine(settings.database_url)

    if args.once:
        ingest_snapshot(settings=settings)
        return

    interval_minutes = args.interval_minutes or settings.ingest_interval_minutes
    logger.info("Starting continuous ingestion every %s minutes", interval_minutes)

    while True:
        try:
            ingest_snapshot(settings=settings)
        except Exception:
            logger.exception("Ingestion cycle failed")
        time.sleep(interval_minutes * 60)


if __name__ == "__main__":
    main()
