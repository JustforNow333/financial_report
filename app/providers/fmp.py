from __future__ import annotations

import logging
from datetime import date

import requests

from .base import EodQuoteRow, MarketDataProvider

logger = logging.getLogger(__name__)


class FmpEodBulkProvider(MarketDataProvider):
    def __init__(self, api_key: str, base_url: str, timeout_seconds: float = 30.0) -> None:
        if not api_key:
            raise ValueError("FMP_API_KEY is required for FMP provider")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def fetch_eod_bulk(self, asof_date: date) -> list[EodQuoteRow]:
        url = f"{self.base_url}/stable/eod-bulk"
        params = {
            "date": asof_date.isoformat(),
            "apikey": self.api_key,
        }

        try:
            response = requests.get(url, params=params, timeout=self.timeout_seconds)
            response.raise_for_status()
        except requests.HTTPError:
            snippet = ""
            try:
                snippet = response.text[:300]
            except Exception:
                pass
            logger.error(
                "FMP EOD bulk request failed: status=%s date=%s body_snippet=%s",
                getattr(response, "status_code", "unknown"),
                asof_date,
                snippet,
            )
            raise

        payload = response.json()
        if not isinstance(payload, list):
            logger.warning(
                "FMP EOD bulk returned non-list payload: date=%s type=%s",
                asof_date,
                type(payload).__name__,
            )
            return []

        rows: list[EodQuoteRow] = []
        for item in payload:
            if not isinstance(item, dict):
                continue

            symbol = str(item.get("symbol") or "").strip().upper()
            if not symbol:
                continue

            row_date = _parse_date(item.get("date"), asof_date)
            close = _parse_float(item.get("close"))
            if close is None:
                continue

            rows.append(
                EodQuoteRow(
                    symbol=symbol,
                    date=row_date,
                    open=_parse_float(item.get("open")),
                    high=_parse_float(item.get("high")),
                    low=_parse_float(item.get("low")),
                    close=close,
                    adj_close=_parse_float(item.get("adjClose")),
                    volume=_parse_float(item.get("volume")),
                    name=_parse_str(item.get("name")),
                    exchange=_parse_str(item.get("exchange")),
                )
            )

        return rows


def _parse_date(value: object, fallback: date) -> date:
    if value is None:
        return fallback
    text = str(value).strip()
    if not text:
        return fallback
    try:
        return date.fromisoformat(text)
    except ValueError:
        return fallback


def _parse_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
