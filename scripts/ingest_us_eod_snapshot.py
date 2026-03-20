from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import date, datetime, time as dt_time, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

import pandas_market_calendars as mcal
from dotenv import load_dotenv
from polygon import StocksClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db import get_session, init_engine, remove_session
from app.models import DailyBar, Ticker

EASTERN_TZ = ZoneInfo("America/New_York")
MAX_POLYGON_CALLS_PER_RUN = 5
NON_COMMON_SUFFIXES = {"W", "WS", "WT", "U", "R", "P"}
OTC_SUFFIXES = {"W", "F", "Y", "Q", "U", "R", "L", "Z"}
PREFERRED_SEP_PATTERN = re.compile(r"[-.]P[A-Z]*$")


class PolygonCallBudget:
    def __init__(self, max_calls: int) -> None:
        self.max_calls = max_calls
        self.calls = 0

    def reserve(self) -> None:
        self.calls += 1
        if self.calls > self.max_calls:
            raise RuntimeError(
                f"Polygon call budget exceeded: {self.calls} > {self.max_calls}. "
                "Free tier limit is 5 requests/minute."
            )


def _resolve_sessions(as_of_date: date | None) -> tuple[date, date]:
    cal = mcal.get_calendar("NYSE")

    if as_of_date is None:
        now_et = datetime.now(EASTERN_TZ)
        candidate = now_et.date()
        if now_et.timetz().replace(tzinfo=None) < dt_time(16, 30):
            candidate -= timedelta(days=1)
    else:
        candidate = as_of_date

    schedule = cal.schedule(
        start_date=(candidate - timedelta(days=20)).isoformat(),
        end_date=candidate.isoformat(),
    )
    sessions = [item.date() for item in schedule.index.to_pydatetime()]
    if len(sessions) < 2:
        raise RuntimeError("Unable to resolve as-of and previous NYSE sessions")

    target = sessions[-1]
    if target > candidate:
        eligible = [item for item in sessions if item <= candidate]
        if not eligible:
            raise RuntimeError("No eligible NYSE session for candidate date")
        target = eligible[-1]

    idx = sessions.index(target)
    if idx == 0:
        raise RuntimeError("Unable to resolve previous NYSE session")

    return target, sessions[idx - 1]


def _call_grouped_daily_bars(
    client: StocksClient,
    *,
    trading_date: date,
    budget: PolygonCallBudget,
    max_retries: int = 2,
):
    backoff = 1.0
    for attempt in range(max_retries + 1):
        if attempt > 0:
            time.sleep(backoff)
            backoff *= 2

        time.sleep(1.0)  # explicit guard: no faster than 1 req/second
        budget.reserve()
        try:
            return client.get_grouped_daily_bars(
                trading_date.isoformat(),
                adjusted=True,
                raw_response=True,
            )
        except Exception:
            if attempt >= max_retries:
                raise

    raise RuntimeError("unreachable retry loop")


def _extract_results(response: object) -> list[object]:
    if response is None:
        return []
    if isinstance(response, dict):
        status = str(response.get("status", "")).strip().upper()
        error = response.get("error")
        if status == "ERROR" or error:
            detail = str(error or response.get("message") or "Unknown Polygon API error").strip()
            raise RuntimeError(f"Polygon grouped daily bars request failed: {detail}")
        rows = response.get("results")
        return rows if isinstance(rows, list) else []
    if hasattr(response, "json"):
        try:
            payload = response.json()
        except Exception:
            return []
        if isinstance(payload, dict):
            status = str(payload.get("status", "")).strip().upper()
            error = payload.get("error")
            if status == "ERROR" or error:
                detail = str(error or payload.get("message") or "Unknown Polygon API error").strip()
                raise RuntimeError(f"Polygon grouped daily bars request failed: {detail}")
            rows = payload.get("results")
            return rows if isinstance(rows, list) else []
    return []


def _field(item: object, *keys: str):
    for key in keys:
        if isinstance(item, dict) and key in item:
            return item[key]
        if hasattr(item, key):
            return getattr(item, key)
    return None


def _build_prev_close_map(prev_rows: list[object]) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in prev_rows:
        ticker_raw = _field(row, "T", "ticker", "symbol")
        close_raw = _field(row, "c", "close")
        if not ticker_raw or close_raw is None:
            continue
        try:
            close = float(close_raw)
        except (TypeError, ValueError):
            continue
        if close <= 0:
            continue
        out[str(ticker_raw).strip().upper()] = close
    return out


def _upsert_daily_bars(session: Session, rows: list[dict[str, object]]) -> int:
    if not rows:
        return 0

    bind = session.bind
    if bind is None:
        raise RuntimeError("Session bind is not available")

    dialect = bind.dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        stmt = pg_insert(DailyBar)
        stmt = stmt.on_conflict_do_update(
            index_elements=["date", "ticker"],
            set_={
                "close": stmt.excluded.close,
                "pct_change": stmt.excluded.pct_change,
                "volume": stmt.excluded.volume,
            },
        )
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        stmt = sqlite_insert(DailyBar)
        stmt = stmt.on_conflict_do_update(
            index_elements=["date", "ticker"],
            set_={
                "close": stmt.excluded.close,
                "pct_change": stmt.excluded.pct_change,
                "volume": stmt.excluded.volume,
            },
        )
    else:
        raise RuntimeError(f"Unsupported SQL dialect for upsert: {dialect}")

    session.execute(stmt, rows)
    return len(rows)


def _load_sec_ticker_set(session: Session) -> set[str]:
    values = session.execute(select(Ticker.ticker)).scalars().all()
    return {str(value).strip().upper() for value in values if value}


def _is_non_common_equity_ticker(ticker: str) -> bool:
    value = ticker.upper().strip()
    if not value:
        return True

    # Prefer/rights/warrants often use separator suffixes: ABC-P, ABC.P, ABC-WS
    if PREFERRED_SEP_PATTERN.search(value):
        return True
    if "-" in value or "." in value:
        suffix = value.replace("-", ".").split(".")[-1]
        if suffix in NON_COMMON_SUFFIXES:
            return True

    # Common warrant/unit/right conventions, mostly 5-char derivatives.
    if len(value) >= 5 and (value.endswith("WS") or value.endswith("WT")):
        return True
    if len(value) == 5 and value[-1] in OTC_SUFFIXES:
        return True
    if len(value) >= 5 and value[-1] in {"W", "U", "R"}:
        return True

    return False


def ingest_us_eod_snapshot(as_of_date: date | None = None) -> dict[str, object]:
    api_key = os.getenv("POLYGON_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("POLYGON_API_KEY is required")

    as_of, prev = _resolve_sessions(as_of_date)
    budget = PolygonCallBudget(MAX_POLYGON_CALLS_PER_RUN)

    client = StocksClient(api_key)
    try:
        # Exactly two Polygon endpoint calls in normal run flow.
        today_resp = _call_grouped_daily_bars(client, trading_date=as_of, budget=budget)
        prev_resp = _call_grouped_daily_bars(client, trading_date=prev, budget=budget)
    finally:
        close_fn = getattr(client, "close", None)
        if callable(close_fn):
            close_fn()

    today_rows = _extract_results(today_resp)
    prev_rows = _extract_results(prev_resp)

    if not today_rows:
        raise RuntimeError(
            "Polygon grouped daily bars returned no rows for as_of_date="
            f"{as_of.isoformat()}. No data was written."
        )

    prev_close_map = _build_prev_close_map(prev_rows)

    session = get_session()
    sec_tickers = _load_sec_ticker_set(session)
    if not sec_tickers:
        remove_session()
        raise RuntimeError(
            "No SEC ticker map found in DB. Run scripts/update_ticker_company_map.py first."
        )

    output_rows: list[dict[str, object]] = []
    pct_change_computed = 0
    missing_prev_close = 0
    excluded_no_sec_map = 0
    excluded_non_common = 0

    for row in today_rows:
        ticker_raw = _field(row, "T", "ticker", "symbol")
        close_raw = _field(row, "c", "close")
        volume_raw = _field(row, "v", "volume")

        if not ticker_raw or close_raw is None:
            continue

        ticker = str(ticker_raw).strip().upper()
        if not ticker:
            continue
        if ticker not in sec_tickers:
            excluded_no_sec_map += 1
            continue
        if _is_non_common_equity_ticker(ticker):
            excluded_non_common += 1
            continue

        try:
            close = float(close_raw)
        except (TypeError, ValueError):
            continue
        if close <= 0:
            continue

        volume = None
        if volume_raw is not None:
            try:
                volume = int(volume_raw)
            except (TypeError, ValueError):
                volume = None

        prev_close = prev_close_map.get(ticker)
        if prev_close is None or prev_close == 0:
            pct_change = None
            missing_prev_close += 1
        else:
            pct_change = (close / prev_close) - 1.0
            pct_change_computed += 1

        output_rows.append(
            {
                "date": as_of,
                "ticker": ticker,
                "close": close,
                "pct_change": pct_change,
                "volume": volume,
                "created_at": datetime.now(EASTERN_TZ),
            }
        )

    try:
        # Replace this date's rows so previous unfiltered runs do not linger.
        session.execute(delete(DailyBar).where(DailyBar.date == as_of))
        upserted = _upsert_daily_bars(session, output_rows)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        remove_session()

    return {
        "as_of_date": as_of.isoformat(),
        "prev_trading_date": prev.isoformat(),
        "polygon_calls_made": budget.calls,
        "daily_bars_ingested": upserted,
        "pct_change_computed": pct_change_computed,
        "missing_prev_close_count": missing_prev_close,
        "excluded_no_sec_map_count": excluded_no_sec_map,
        "excluded_non_common_ticker_count": excluded_non_common,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest US EOD close + volume from Polygon grouped daily bars")
    parser.add_argument("--asof-date", type=str, default=None, help="YYYY-MM-DD")
    return parser.parse_args()


def main() -> None:
    load_dotenv()
    args = _parse_args()
    as_of_date = date.fromisoformat(args.asof_date) if args.asof_date else None

    database_url = os.getenv("DATABASE_URL", "sqlite:///fin_daily_report.db")
    init_engine(database_url)

    summary = ingest_us_eod_snapshot(as_of_date=as_of_date)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
