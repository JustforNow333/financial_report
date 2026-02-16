from __future__ import annotations

import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import func
from sqlalchemy.orm import Session

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db import get_session, init_engine, remove_session
from app.models import Ticker

INPUT_CSV_PATH = Path("data/sec_company_ticker_industry.csv")


def _parse_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise RuntimeError(f"CSV not found: {path}")

    rows: list[dict[str, Any]] = []
    with path.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for raw in reader:
            ticker = str(raw.get("ticker") or "").strip().upper()
            company_name = str(raw.get("company_name") or "").strip()
            if not ticker or not company_name:
                continue

            exchange_raw = raw.get("exchange")
            exchange = str(exchange_raw).strip() if exchange_raw else None

            sic_description_raw = raw.get("sic_description")
            sic_description = (
                str(sic_description_raw).strip() if sic_description_raw not in (None, "") else None
            )

            rows.append(
                {
                    "ticker": ticker,
                    "company_name": company_name,
                    "cik": _parse_int(raw.get("cik")),
                    "exchange": exchange,
                    "sic_code": _parse_int(raw.get("sic_code")),
                    "sic_description": sic_description,
                }
            )

    rows.sort(key=lambda row: str(row["ticker"]))
    return rows


def _upsert_tickers(session: Session, rows: list[dict[str, Any]]) -> int:
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
        excluded = stmt.excluded
        stmt = stmt.on_conflict_do_update(
            index_elements=["ticker"],
            set_={
                "company_name": excluded.company_name,
                "cik": func.coalesce(excluded.cik, Ticker.cik),
                "exchange": func.coalesce(excluded.exchange, Ticker.exchange),
                "sic_code": func.coalesce(excluded.sic_code, Ticker.sic_code),
                "sic_description": func.coalesce(excluded.sic_description, Ticker.sic_description),
                "updated_at": excluded.updated_at,
            },
        )
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        stmt = sqlite_insert(Ticker)
        excluded = stmt.excluded
        stmt = stmt.on_conflict_do_update(
            index_elements=["ticker"],
            set_={
                "company_name": excluded.company_name,
                "cik": func.coalesce(excluded.cik, Ticker.cik),
                "exchange": func.coalesce(excluded.exchange, Ticker.exchange),
                "sic_code": func.coalesce(excluded.sic_code, Ticker.sic_code),
                "sic_description": func.coalesce(excluded.sic_description, Ticker.sic_description),
                "updated_at": excluded.updated_at,
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

    rows = _read_csv(INPUT_CSV_PATH)

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
                "input_csv_path": str(INPUT_CSV_PATH),
                "rows_in_csv": len(rows),
                "rows_upserted": upserted,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
