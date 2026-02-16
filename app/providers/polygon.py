from __future__ import annotations

from datetime import date

from polygon import StocksClient

from .base import EodQuoteRow, MarketDataProvider


class PolygonSnapshotProvider(MarketDataProvider):
    def __init__(self, api_key: str, base_url: str, timeout_seconds: float = 30.0) -> None:
        if not api_key:
            raise ValueError("POLYGON_API_KEY is required for Polygon provider")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def fetch_eod_bulk(self, asof_date: date) -> list[EodQuoteRow]:
        # Grouped daily bars returns one row per ticker for the requested date.
        client = StocksClient(self.api_key)
        try:
            response = client.get_grouped_daily_bars(asof_date.isoformat(), adjusted=True)
        finally:
            close_fn = getattr(client, "close", None)
            if callable(close_fn):
                close_fn()

        rows = _extract_results(response)
        parsed: list[EodQuoteRow] = []
        for item in rows:
            ticker = _extract_ticker(item)
            close = _extract_close(item)
            if not ticker or close is None:
                continue
            parsed.append(
                EodQuoteRow(
                    symbol=ticker,
                    date=asof_date,
                    open=_extract_float(item, "o", "open"),
                    high=_extract_float(item, "h", "high"),
                    low=_extract_float(item, "l", "low"),
                    close=close,
                    adj_close=close,
                    volume=_extract_float(item, "v", "volume"),
                )
            )

        return parsed


def _extract_results(response: object) -> list[object]:
    if response is None:
        return []
    if isinstance(response, list):
        return response
    if isinstance(response, dict):
        value = response.get("results")
        return value if isinstance(value, list) else []
    value = getattr(response, "results", None)
    return value if isinstance(value, list) else []


def _extract_ticker(row: object) -> str | None:
    value = _extract_field(row, "T", "ticker", "symbol")
    if value is None:
        return None
    ticker = str(value).strip().upper()
    return ticker or None


def _extract_close(row: object) -> float | None:
    return _extract_float(row, "c", "close")


def _extract_float(row: object, *keys: str) -> float | None:
    value = _extract_field(row, *keys)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_field(row: object, *keys: str) -> object | None:
    for key in keys:
        if isinstance(row, dict) and key in row:
            return row[key]
        if hasattr(row, key):
            return getattr(row, key)
    return None
