from __future__ import annotations

from datetime import datetime
from urllib.parse import urljoin

import requests

from .base import MarketSnapshotProvider, SnapshotQuote


class PolygonSnapshotProvider(MarketSnapshotProvider):
    def __init__(self, api_key: str, base_url: str, timeout_seconds: float = 30.0) -> None:
        if not api_key:
            raise ValueError("POLYGON_API_KEY is required for Polygon provider")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def fetch_snapshot(self, asof_ts: datetime) -> list[SnapshotQuote]:
        url = f"{self.base_url}/v2/snapshot/locale/us/markets/stocks/tickers"
        params: dict[str, str] | None = {"apiKey": self.api_key}

        quotes: list[SnapshotQuote] = []
        while url:
            response = requests.get(url, params=params, timeout=self.timeout_seconds)
            response.raise_for_status()
            payload = response.json()

            for item in payload.get("tickers", []):
                quote = self._parse_item(item)
                if quote.ticker:
                    quotes.append(quote)

            next_url = payload.get("next_url")
            if not next_url:
                break

            url = next_url if next_url.startswith("http") else urljoin(self.base_url, next_url)
            params = {"apiKey": self.api_key}

        return quotes

    @staticmethod
    def _parse_item(item: dict[str, object]) -> SnapshotQuote:
        day_data = item.get("day") if isinstance(item.get("day"), dict) else {}
        prev_day = item.get("prevDay") if isinstance(item.get("prevDay"), dict) else {}
        last_trade = item.get("lastTrade") if isinstance(item.get("lastTrade"), dict) else {}

        last_price = _as_float(last_trade.get("p"))
        if last_price is None:
            last_price = _as_float(day_data.get("c"))

        return SnapshotQuote(
            ticker=str(item.get("ticker") or "").upper(),
            name=_as_optional_str(item.get("name")),
            exchange=_as_optional_str(item.get("primary_exchange")),
            last_price=last_price,
            prev_close=_as_float(prev_day.get("c")),
            day_open=_as_float(day_data.get("o")),
            day_high=_as_float(day_data.get("h")),
            day_low=_as_float(day_data.get("l")),
            day_volume=_as_int(day_data.get("v")),
        )


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
