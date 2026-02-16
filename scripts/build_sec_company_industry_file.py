from __future__ import annotations

import csv
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SEC_SUBMISSIONS_URL_TEMPLATE = "https://data.sec.gov/submissions/CIK{cik}.json"

CACHE_DIR = Path("data/cache")
SUBMISSIONS_CACHE_DIR = CACHE_DIR / "submissions"
COMPANY_TICKERS_CACHE_PATH = CACHE_DIR / "company_tickers_exchange.json"

OUTPUT_CSV_PATH = Path("data/sec_company_ticker_industry.csv")
OUTPUT_JSON_PATH = Path("data/sec_company_ticker_industry.json")

COMPANY_TICKERS_CACHE_MAX_AGE = timedelta(days=7)
SUBMISSIONS_CACHE_MAX_AGE = timedelta(days=30)

MAX_RETRIES = 3
REQUEST_TIMEOUT = 30
MAX_REQUESTS_PER_SECOND = 2.0

INSTRUMENT_SUFFIX_PATTERN = re.compile(
    r"(?:[-.](?:W|WS|WT|R|RT|U|UN|RIGHT|WARRANT|UNIT)\d*)$",
    re.IGNORECASE,
)


@dataclass
class RateLimiter:
    max_requests_per_second: float
    _last_request_monotonic: float | None = None

    def wait(self) -> None:
        min_interval = 1.0 / self.max_requests_per_second
        now = time.monotonic()
        if self._last_request_monotonic is not None:
            elapsed = now - self._last_request_monotonic
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
        self._last_request_monotonic = time.monotonic()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _is_fresh(path: Path, max_age: timedelta) -> bool:
    if not path.exists():
        return False
    age = _now_utc() - datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return age <= max_age


def _require_user_agent() -> str:
    user_agent = os.getenv("SEC_USER_AGENT", "").strip()
    if user_agent:
        return user_agent
    raise RuntimeError("SEC_USER_AGENT is required (example: 'YahooFinanceLite ops@example.com')")


def _get_json_with_retry(
    *,
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    limiter: RateLimiter,
) -> dict[str, Any]:
    backoff = 1.0
    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES + 1):
        limiter.wait()
        try:
            response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            last_error = exc
            if attempt >= MAX_RETRIES:
                break
            time.sleep(backoff)
            backoff *= 2
            continue

        status = response.status_code
        if status in {403, 429} or status >= 500:
            last_error = RuntimeError(f"{url} returned HTTP {status}")
            if attempt >= MAX_RETRIES:
                break
            time.sleep(backoff)
            backoff *= 2
            continue

        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError(f"Unexpected JSON payload type from {url}")
        return payload

    raise RuntimeError(f"Failed to fetch {url} after retries: {last_error}")


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected JSON structure in {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)


def _format_cik(cik: int | str) -> str:
    try:
        value = int(str(cik).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid CIK value: {cik!r}") from exc
    if value < 0:
        raise ValueError(f"CIK must be non-negative: {cik!r}")
    return f"{value:010d}"


def _is_company_ticker(ticker: str) -> bool:
    value = ticker.strip().upper()
    if not value:
        return False
    if INSTRUMENT_SUFFIX_PATTERN.search(value):
        return False
    return True


def _company_ticker_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    fields = payload.get("fields")
    data = payload.get("data")
    if not isinstance(fields, list) or not isinstance(data, list):
        raise RuntimeError("SEC mapping payload missing fields/data")

    index_map = {str(name): idx for idx, name in enumerate(fields)}
    required = {"ticker", "name", "cik", "exchange"}
    if not required.issubset(index_map):
        raise RuntimeError("SEC mapping payload does not contain required columns")

    rows: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, list):
            continue

        ticker = str(item[index_map["ticker"]] or "").strip().upper()
        company_name = str(item[index_map["name"]] or "").strip()
        exchange_raw = item[index_map["exchange"]]
        exchange = str(exchange_raw).strip() if exchange_raw else None

        if not ticker or not company_name:
            continue
        if not _is_company_ticker(ticker):
            continue

        cik_raw = item[index_map["cik"]]
        try:
            cik = int(str(cik_raw).strip()) if cik_raw not in (None, "") else None
        except (TypeError, ValueError):
            cik = None
        if cik is None:
            continue

        rows.append(
            {
                "ticker": ticker,
                "company_name": company_name,
                "cik": cik,
                "exchange": exchange,
            }
        )

    rows.sort(key=lambda row: row["ticker"])
    return rows


def _extract_sic_fields(submissions_payload: dict[str, Any]) -> tuple[int | None, str | None]:
    sic_value = submissions_payload.get("sic")
    sic_description_value = submissions_payload.get("sicDescription")

    sic_code: int | None = None
    if sic_value not in (None, ""):
        try:
            sic_code = int(str(sic_value).strip())
        except (TypeError, ValueError):
            sic_code = None

    sic_description: str | None = None
    if sic_description_value not in (None, ""):
        text = str(sic_description_value).strip()
        sic_description = text or None

    return sic_code, sic_description


def _load_company_tickers_payload(session: requests.Session, limiter: RateLimiter, user_agent: str) -> dict[str, Any]:
    if _is_fresh(COMPANY_TICKERS_CACHE_PATH, COMPANY_TICKERS_CACHE_MAX_AGE):
        return _read_json(COMPANY_TICKERS_CACHE_PATH)

    payload = _get_json_with_retry(
        session=session,
        url=SEC_TICKERS_URL,
        headers={
            "User-Agent": user_agent,
            "Accept-Encoding": "gzip, deflate",
            "Host": "www.sec.gov",
        },
        limiter=limiter,
    )
    _write_json(COMPANY_TICKERS_CACHE_PATH, payload)
    return payload


def _load_submissions_payload(
    session: requests.Session,
    limiter: RateLimiter,
    user_agent: str,
    cik_padded: str,
) -> dict[str, Any]:
    cache_path = SUBMISSIONS_CACHE_DIR / f"CIK{cik_padded}.json"
    if _is_fresh(cache_path, SUBMISSIONS_CACHE_MAX_AGE):
        return _read_json(cache_path)

    payload = _get_json_with_retry(
        session=session,
        url=SEC_SUBMISSIONS_URL_TEMPLATE.format(cik=cik_padded),
        headers={
            "User-Agent": user_agent,
            "Accept-Encoding": "gzip, deflate",
            "Host": "data.sec.gov",
        },
        limiter=limiter,
    )
    _write_json(cache_path, payload)
    return payload


def _build_rows() -> list[dict[str, Any]]:
    load_dotenv()
    user_agent = _require_user_agent()

    limiter = RateLimiter(max_requests_per_second=MAX_REQUESTS_PER_SECOND)
    rows: list[dict[str, Any]] = []
    updated_at = _now_utc().isoformat()

    with requests.Session() as session:
        payload = _load_company_tickers_payload(session, limiter, user_agent)
        base_rows = _company_ticker_rows(payload)

        for base_row in base_rows:
            cik_padded = _format_cik(base_row["cik"])
            submissions = _load_submissions_payload(session, limiter, user_agent, cik_padded)
            sic_code, sic_description = _extract_sic_fields(submissions)

            rows.append(
                {
                    "ticker": base_row["ticker"],
                    "company_name": base_row["company_name"],
                    "cik": base_row["cik"],
                    "exchange": base_row["exchange"],
                    "sic_code": sic_code,
                    "sic_description": sic_description,
                    "source": "SEC",
                    "updated_at": updated_at,
                }
            )

    rows.sort(key=lambda row: row["ticker"])
    return rows


def _write_outputs(rows: list[dict[str, Any]]) -> None:
    OUTPUT_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "ticker",
        "company_name",
        "cik",
        "exchange",
        "sic_code",
        "sic_description",
        "source",
        "updated_at",
    ]

    with OUTPUT_CSV_PATH.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    with OUTPUT_JSON_PATH.open("w", encoding="utf-8") as fh:
        json.dump(rows, fh, indent=2, sort_keys=False)


def main() -> None:
    rows = _build_rows()
    _write_outputs(rows)

    sic_present = sum(1 for row in rows if row.get("sic_code") is not None)
    sic_missing = len(rows) - sic_present

    print(
        json.dumps(
            {
                "total_tickers_processed": len(rows),
                "tickers_with_sic_present": sic_present,
                "tickers_missing_sic": sic_missing,
                "output_csv_path": str(OUTPUT_CSV_PATH),
                "output_csv_row_count": len(rows),
                "output_json_path": str(OUTPUT_JSON_PATH),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
