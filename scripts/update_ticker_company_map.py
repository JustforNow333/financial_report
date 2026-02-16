from __future__ import annotations

import csv
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
from sqlalchemy.orm import Session

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db import get_session, init_engine, remove_session
from app.models import Ticker

SEC_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
CSV_PATH = Path("data/us_ticker_company_map.csv")
CACHE_MAX_AGE = timedelta(days=7)


def _is_cache_fresh(path: Path) -> bool:
    if not path.exists():
        return False
    age = datetime.now(timezone.utc) - datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return age < CACHE_MAX_AGE


def _download_sec_json() -> dict[str, object]:
    user_agent = os.getenv("SEC_USER_AGENT", "").strip()
    if not user_agent:
        raise RuntimeError(
            "SEC_USER_AGENT is required. Example: 'MyApp myemail@example.com'"
        )

    response = requests.get(
        SEC_URL,
        headers={
            "User-Agent": user_agent,
            "Accept-Encoding": "gzip, deflate",
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("Unexpected SEC payload format")
    return payload


def _sec_payload_to_rows(payload: dict[str, object]) -> list[dict[str, object]]:
    fields = payload.get("fields")
    data = payload.get("data")
    if not isinstance(fields, list) or not isinstance(data, list):
        raise RuntimeError("SEC payload missing fields/data arrays")

    index_map = {str(name): idx for idx, name in enumerate(fields)}
    required = {"ticker", "name", "cik", "exchange"}
    if not required.issubset(index_map.keys()):
        raise RuntimeError("SEC payload does not include required columns")

    rows: list[dict[str, object]] = []
    for entry in data:
        if not isinstance(entry, list):
            continue
        ticker = str(entry[index_map["ticker"]] or "").strip().upper()
        company_name = str(entry[index_map["name"]] or "").strip()
        if not ticker or not company_name:
            continue

        cik_raw = entry[index_map["cik"]]
        cik_value = None
        if cik_raw not in (None, ""):
            try:
                cik_value = int(cik_raw)
            except (TypeError, ValueError):
                cik_value = None

        exchange_value = entry[index_map["exchange"]]
        exchange = str(exchange_value).strip() if exchange_value else None

        rows.append(
            {
                "ticker": ticker,
                "company_name": company_name,
                "cik": cik_value,
                "exchange": exchange,
            }
        )

    return rows


def _write_csv(rows: list[dict[str, object]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["ticker", "company_name", "cik", "exchange"],
        )
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict[str, object]]:
    with path.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows: list[dict[str, object]] = []
        for row in reader:
            ticker = str(row.get("ticker") or "").strip().upper()
            company_name = str(row.get("company_name") or "").strip()
            if not ticker or not company_name:
                continue
            cik_raw = row.get("cik")
            cik_value = None
            if cik_raw:
                try:
                    cik_value = int(cik_raw)
                except (TypeError, ValueError):
                    cik_value = None
            exchange_raw = row.get("exchange")
            exchange = str(exchange_raw).strip() if exchange_raw else None
            rows.append(
                {
                    "ticker": ticker,
                    "company_name": company_name,
                    "cik": cik_value,
                    "exchange": exchange,
                }
            )
        return rows


def _upsert_tickers(session: Session, rows: list[dict[str, object]]) -> int:
    if not rows:
        return 0

    bind = session.bind
    if bind is None:
        raise RuntimeError("Session bind is not available")

    now_utc = datetime.now(timezone.utc)
    payload = [{**row, "updated_at": now_utc} for row in rows]

    dialect = bind.dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        stmt = pg_insert(Ticker)
        stmt = stmt.on_conflict_do_update(
            index_elements=["ticker"],
            set_={
                "company_name": stmt.excluded.company_name,
                "cik": stmt.excluded.cik,
                "exchange": stmt.excluded.exchange,
                "updated_at": stmt.excluded.updated_at,
            },
        )
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        stmt = sqlite_insert(Ticker)
        stmt = stmt.on_conflict_do_update(
            index_elements=["ticker"],
            set_={
                "company_name": stmt.excluded.company_name,
                "cik": stmt.excluded.cik,
                "exchange": stmt.excluded.exchange,
                "updated_at": stmt.excluded.updated_at,
            },
        )
    else:
        raise RuntimeError(f"Unsupported SQL dialect for upsert: {dialect}")

    session.execute(stmt, payload)
    return len(payload)


def main() -> None:
    load_dotenv()
    database_url = os.getenv("DATABASE_URL", "sqlite:///fin_daily_report.db")
    init_engine(database_url)

    downloaded = False
    if _is_cache_fresh(CSV_PATH):
        rows = _read_csv(CSV_PATH)
    else:
        payload = _download_sec_json()
        rows = _sec_payload_to_rows(payload)
        _write_csv(rows, CSV_PATH)
        downloaded = True

    session = get_session()
    try:
        upserted = _upsert_tickers(session, rows)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        remove_session()

    print(
        json.dumps(
            {
                "csv_path": str(CSV_PATH),
                "downloaded": downloaded,
                "tickers_in_csv": len(rows),
                "tickers_upserted": upserted,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
