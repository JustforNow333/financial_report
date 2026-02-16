from __future__ import annotations

import argparse
import logging
import os
import time
from datetime import date, datetime, time as dt_time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pandas_market_calendars as mcal
from polygon import StocksClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session, init_engine, remove_session
from app.models import Company, DailyReturn, PriceDaily, Symbol

logger = logging.getLogger(__name__)
EASTERN_TZ = ZoneInfo("America/New_York")


def compute_pct_change(close: float | None, prev_close: float | None) -> float | None:
    if close is None or prev_close is None or prev_close <= 0:
        return None
    return (close / prev_close) - 1.0


def ingest_us_eod_snapshot(as_of_date: date | None = None) -> dict[str, object]:
    """
    Ingest one US EOD market snapshot from Polygon grouped daily bars.

    Normal path uses exactly 2 Polygon REST calls:
    1) as-of trading session grouped daily bars
    2) previous trading session grouped daily bars
    """
    api_key = os.environ["POLYGON_API_KEY"]

    target_date, prev_date = _resolve_target_and_previous_session(as_of_date)
    logger.info("Resolved trading dates: as_of_date=%s prev_trading_date=%s", target_date, prev_date)

    client = StocksClient(api_key)
    try:
        # Target: exactly two API calls in the normal path.
        r_today = _get_grouped_daily_bars_with_backoff(client, target_date)
        r_prev = _get_grouped_daily_bars_with_backoff(client, prev_date)
    finally:
        close_fn = getattr(client, "close", None)
        if callable(close_fn):
            close_fn()

    today_rows = _extract_results(r_today)
    prev_rows = _extract_results(r_prev)

    if not today_rows:
        raise RuntimeError(
            "Polygon grouped daily bars returned no rows for as_of_date="
            f"{target_date.isoformat()}. No data was written."
        )

    prev_close_by_ticker: dict[str, float] = {}
    for row in prev_rows:
        ticker = _extract_ticker(row)
        close = _extract_close(row)
        if not ticker or close is None:
            continue
        prev_close_by_ticker[ticker] = close

    processed_rows: list[dict[str, object]] = []
    pct_change_computed = 0
    missing_prev_close = 0

    for row in today_rows:
        ticker = _extract_ticker(row)
        close_today = _extract_close(row)
        if not ticker or close_today is None:
            continue

        close_prev = prev_close_by_ticker.get(ticker)
        pct_change = compute_pct_change(close_today, close_prev)
        if pct_change is None:
            missing_prev_close += 1
        else:
            pct_change_computed += 1

        processed_rows.append(
            {
                "ticker": ticker,
                "close": close_today,
                "prev_close": close_prev,
                "pct_change": pct_change,
            }
        )

    session = get_session()
    try:
        _upsert_symbol_and_company_rows(session, processed_rows)
        rows_ingested, rows_updated = _upsert_daily_snapshot_rows(
            session,
            as_of_date=target_date,
            prev_trading_date=prev_date,
            processed_rows=processed_rows,
        )
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("Polygon EOD ingest failed")
        raise
    finally:
        remove_session()

    summary = {
        "as_of_date": target_date.isoformat(),
        "prev_trading_date": prev_date.isoformat(),
        "tickers_processed": len(processed_rows),
        "pct_change_computed": pct_change_computed,
        "missing_prev_close": missing_prev_close,
        "rows_ingested": rows_ingested,
        "rows_updated": rows_updated,
    }
    logger.info("Polygon EOD ingest complete: %s", summary)
    return summary


def _resolve_target_and_previous_session(as_of_date: date | None) -> tuple[date, date]:
    cal = mcal.get_calendar("NYSE")

    if as_of_date is None:
        now_et = datetime.now(EASTERN_TZ)
        candidate = now_et.date()
        if now_et.timetz().replace(tzinfo=None) < dt_time(16, 30):
            candidate = candidate - timedelta(days=1)
    else:
        candidate = as_of_date

    schedule = cal.schedule(
        start_date=(candidate - timedelta(days=20)).isoformat(),
        end_date=candidate.isoformat(),
    )
    session_dates = [d.date() for d in schedule.index.to_pydatetime()]
    if len(session_dates) < 2:
        raise RuntimeError("Unable to resolve NYSE sessions for as-of and previous trading day")

    target = session_dates[-1]
    if target > candidate:
        candidates = [d for d in session_dates if d <= candidate]
        if not candidates:
            raise RuntimeError("Unable to find prior NYSE trading session")
        target = candidates[-1]

    target_index = session_dates.index(target)
    if target_index == 0:
        raise RuntimeError("Unable to resolve previous NYSE trading session")

    prev = session_dates[target_index - 1]
    return target, prev


def _get_grouped_daily_bars_with_backoff(
    client: StocksClient,
    trading_date: date,
    *,
    adjusted: bool = True,
    max_attempts: int = 3,
) -> Any:
    wait_seconds = 1.0
    for attempt in range(1, max_attempts + 1):
        if attempt > 1:
            time.sleep(wait_seconds)
            wait_seconds *= 2

        # Free-tier safety guard: minimum one request per second.
        time.sleep(1.0)

        try:
            return client.get_grouped_daily_bars(
                trading_date.isoformat(),
                adjusted=adjusted,
                raw_response=True,
            )
        except Exception:
            if attempt == max_attempts:
                raise
            logger.warning(
                "Transient grouped daily bars error; retrying: date=%s attempt=%s",
                trading_date,
                attempt,
            )

    raise RuntimeError("Unreachable retry loop")


def _extract_results(response: Any) -> list[Any]:
    if response is None:
        return []
    if isinstance(response, list):
        return response
    if isinstance(response, tuple):
        return list(response)
    if isinstance(response, dict):
        value = response.get("results")
        return value if isinstance(value, list) else []
    if hasattr(response, "results"):
        value = getattr(response, "results")
        return value if isinstance(value, list) else []
    if hasattr(response, "json"):
        try:
            payload = response.json()
        except Exception:
            return []
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            value = payload.get("results")
            if isinstance(value, list):
                return value
    if hasattr(response, "__iter__") and not isinstance(response, (str, bytes)):
        try:
            return list(response)
        except Exception:
            return []
    return []


def _extract_ticker(row: Any) -> str | None:
    ticker = _read_field(row, "T", "ticker", "symbol")
    if ticker is None:
        return None
    text = str(ticker).strip().upper()
    return text or None


def _extract_close(row: Any) -> float | None:
    value = _read_field(row, "c", "close")
    if value is None:
        return None
    try:
        close = float(value)
    except (TypeError, ValueError):
        return None
    return close if close > 0 else None


def _read_field(obj: Any, *keys: str) -> Any:
    for key in keys:
        if isinstance(obj, dict) and key in obj:
            return obj[key]
        if hasattr(obj, key):
            return getattr(obj, key)
    return None


def _upsert_symbol_and_company_rows(session: Session, processed_rows: list[dict[str, object]]) -> None:
    tickers = sorted({str(row["ticker"]) for row in processed_rows})
    if not tickers:
        return

    existing_symbols = {
        symbol.ticker: symbol
        for symbol in session.execute(select(Symbol).where(Symbol.ticker.in_(tickers))).scalars().all()
    }
    existing_companies = {
        company.symbol: company
        for company in session.execute(select(Company).where(Company.symbol.in_(tickers))).scalars().all()
    }

    for ticker in tickers:
        if ticker not in existing_symbols:
            session.add(Symbol(ticker=ticker, active=True))
        if ticker not in existing_companies:
            session.add(Company(symbol=ticker))


def _upsert_daily_snapshot_rows(
    session: Session,
    *,
    as_of_date: date,
    prev_trading_date: date,
    processed_rows: list[dict[str, object]],
) -> tuple[int, int]:
    if not processed_rows:
        return 0, 0

    bind = session.bind
    if bind is None:
        raise RuntimeError("Session bind is not available")

    symbols = [str(row["ticker"]) for row in processed_rows]

    existing_rows = session.execute(
        select(PriceDaily.symbol)
        .where(PriceDaily.date == as_of_date, PriceDaily.symbol.in_(symbols))
    ).scalars().all()
    existing_set = set(existing_rows)

    price_payload = [
        {
            "symbol": str(row["ticker"]),
            "date": as_of_date,
            "open": None,
            "high": None,
            "low": None,
            "close": float(row["close"]),
            "adj_close": None,
            "volume": None,
            "source": "polygon_grouped_daily_bars",
        }
        for row in processed_rows
    ]

    returns_payload = [
        {
            "symbol": str(row["ticker"]),
            "date": as_of_date,
            "prev_date": prev_trading_date,
            "close": float(row["close"]),
            "prev_close": row["prev_close"],
            "pct_change": row["pct_change"],
            "is_outlier": False,
            "outlier_reason": None,
        }
        for row in processed_rows
    ]

    dialect = bind.dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        price_stmt = pg_insert(PriceDaily)
        price_stmt = price_stmt.on_conflict_do_update(
            index_elements=["symbol", "date"],
            set_={
                "close": price_stmt.excluded.close,
                "source": price_stmt.excluded.source,
            },
        )

        ret_stmt = pg_insert(DailyReturn)
        ret_stmt = ret_stmt.on_conflict_do_update(
            index_elements=["symbol", "date"],
            set_={
                "close": ret_stmt.excluded.close,
                "prev_date": ret_stmt.excluded.prev_date,
                "prev_close": ret_stmt.excluded.prev_close,
                "pct_change": ret_stmt.excluded.pct_change,
                "is_outlier": ret_stmt.excluded.is_outlier,
                "outlier_reason": ret_stmt.excluded.outlier_reason,
            },
        )
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        price_stmt = sqlite_insert(PriceDaily)
        price_stmt = price_stmt.on_conflict_do_update(
            index_elements=["symbol", "date"],
            set_={
                "close": price_stmt.excluded.close,
                "source": price_stmt.excluded.source,
            },
        )

        ret_stmt = sqlite_insert(DailyReturn)
        ret_stmt = ret_stmt.on_conflict_do_update(
            index_elements=["symbol", "date"],
            set_={
                "close": ret_stmt.excluded.close,
                "prev_date": ret_stmt.excluded.prev_date,
                "prev_close": ret_stmt.excluded.prev_close,
                "pct_change": ret_stmt.excluded.pct_change,
                "is_outlier": ret_stmt.excluded.is_outlier,
                "outlier_reason": ret_stmt.excluded.outlier_reason,
            },
        )
    else:
        raise RuntimeError(f"Unsupported SQL dialect for upsert: {dialect}")

    session.execute(price_stmt, price_payload)
    session.execute(ret_stmt, returns_payload)

    rows_updated = len(existing_set)
    rows_ingested = max(0, len(processed_rows) - rows_updated)
    return rows_ingested, rows_updated


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest US EOD grouped bars from Polygon")
    parser.add_argument("--once", action="store_true", help="Run ingestion once and exit")
    parser.add_argument("--asof-date", type=str, default=None, help="Override ingest date (YYYY-MM-DD)")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = _parse_args()

    database_url = os.getenv("DATABASE_URL", "sqlite:///fin_daily_report.db")
    init_engine(database_url)

    as_of_date = date.fromisoformat(args.asof_date) if args.asof_date else None

    if args.once:
        ingest_us_eod_snapshot(as_of_date=as_of_date)
        return

    ingest_us_eod_snapshot(as_of_date=as_of_date)


if __name__ == "__main__":
    main()
