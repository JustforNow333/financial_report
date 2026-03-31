from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import Settings
from app.db import get_session, init_engine, remove_session
from app.international import ingest_international_snapshots, load_curated_international_companies
from app.providers.eodhd import EodhdInternationalProvider


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest latest-known international company snapshots")
    parser.add_argument(
        "--asof-date",
        type=str,
        default=None,
        help="Override run date / freshness reference in YYYY-MM-DD format",
    )
    parser.add_argument(
        "--universe-path",
        type=str,
        default=None,
        help="Override curated international universe JSON path",
    )
    return parser.parse_args()


def main() -> None:
    load_dotenv()
    args = _parse_args()
    settings = Settings.from_env()

    run_date = date.fromisoformat(args.asof_date) if args.asof_date else None
    universe_path = args.universe_path or settings.international_universe_path

    init_engine(settings.database_url)
    companies = load_curated_international_companies(universe_path)

    provider = EodhdInternationalProvider(
        api_key=settings.eodhd_api_key or "",
        base_url=settings.eodhd_base_url,
        timeout_seconds=settings.request_timeout_seconds,
    )

    session = get_session()
    try:
        summary = ingest_international_snapshots(
            session,
            companies=companies,
            provider=provider,
            run_date=run_date,
            stale_after_days=settings.international_stale_after_days,
        )
        summary["universe_path"] = universe_path
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        close_fn = getattr(provider, "close", None)
        if callable(close_fn):
            close_fn()
        remove_session()

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
