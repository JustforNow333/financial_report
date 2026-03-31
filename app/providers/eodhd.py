from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import requests

from app.international import ExchangeSymbol, FxRateQuote, InternationalQuote


class EodhdInternationalProvider:
    provider_name = "eodhd"

    def __init__(self, api_key: str, base_url: str, timeout_seconds: float = 30.0) -> None:
        if not api_key:
            raise ValueError("EODHD_API_KEY is required for EODHD provider")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()

    def close(self) -> None:
        self.session.close()

    def fetch_latest_quote(self, symbol: str) -> InternationalQuote | None:
        payload = self._get_json(f"/api/real-time/{symbol}")
        if not isinstance(payload, dict):
            return None

        local_price = _parse_float(payload.get("close"))
        if local_price is None:
            local_price = _parse_float(payload.get("price"))

        previous_close = _parse_float(payload.get("previousClose"))
        as_of_date = _parse_date(payload.get("date"))
        price_timestamp_utc = _parse_timestamp(payload.get("timestamp"))
        market_cap = (
            _parse_float(payload.get("market_capitalization"))
            or _parse_float(payload.get("marketCapitalization"))
            or _parse_float(payload.get("market_cap"))
        )

        eod_rows: list[dict[str, Any]] | None = None
        if local_price is None or previous_close is None or as_of_date is None:
            eod_rows = self._fetch_recent_eod_rows(symbol)
            if local_price is None and eod_rows:
                local_price = _parse_float(eod_rows[0].get("close"))
            if as_of_date is None and eod_rows:
                as_of_date = _parse_date(eod_rows[0].get("date"))
            if previous_close is None and eod_rows:
                previous_close = _pick_previous_close(eod_rows, as_of_date)
            if price_timestamp_utc is None and as_of_date is not None:
                price_timestamp_utc = datetime.combine(as_of_date, datetime.min.time(), tzinfo=timezone.utc)

        if local_price is None or as_of_date is None:
            return None

        return InternationalQuote(
            symbol=symbol,
            local_price=local_price,
            previous_local_close=previous_close,
            as_of_date=as_of_date,
            price_timestamp_utc=price_timestamp_utc,
            market_cap=market_cap,
        )

    def fetch_exchange_symbols(self, exchange: str) -> list[ExchangeSymbol]:
        payload = self._get_json(f"/api/exchange-symbol-list/{exchange}")
        if not isinstance(payload, list):
            return []

        symbols: list[ExchangeSymbol] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            code = str(item.get("Code") or item.get("code") or "").strip().upper()
            name = str(item.get("Name") or item.get("name") or "").strip()
            if not code or not name:
                continue
            symbols.append(
                ExchangeSymbol(
                    code=code,
                    name=name,
                    exchange=str(item.get("Exchange") or item.get("exchange") or exchange).strip().upper(),
                    currency=_parse_optional_str(item.get("Currency") or item.get("currency")),
                    country=_parse_optional_str(item.get("Country") or item.get("country")),
                    type=_parse_optional_str(item.get("Type") or item.get("type")),
                )
            )
        return symbols

    def fetch_fx_rate_to_usd(self, currency: str) -> FxRateQuote | None:
        normalized = currency.strip().upper()
        if not normalized:
            return None
        if normalized == "USD":
            return FxRateQuote(currency="USD", rate_to_usd=1.0, fx_timestamp_utc=datetime.now(timezone.utc))

        direct_quote = self._fetch_forex_quote(f"{normalized}USD.FOREX")
        if direct_quote is not None:
            return FxRateQuote(
                currency=normalized,
                rate_to_usd=direct_quote[0],
                fx_timestamp_utc=direct_quote[1],
            )

        inverse_quote = self._fetch_forex_quote(f"{normalized}.FOREX")
        if inverse_quote is None or inverse_quote[0] <= 0:
            return None

        return FxRateQuote(
            currency=normalized,
            rate_to_usd=1.0 / inverse_quote[0],
            fx_timestamp_utc=inverse_quote[1],
        )

    def _fetch_recent_eod_rows(self, symbol: str, limit: int = 2) -> list[dict[str, Any]]:
        payload = self._get_json("/api/eod/" + symbol, params={"order": "d"})
        if not isinstance(payload, list):
            return []
        rows = [item for item in payload if isinstance(item, dict)]
        return rows[:limit]

    def _fetch_forex_quote(self, symbol: str) -> tuple[float, datetime | None] | None:
        try:
            payload = self._get_json(f"/api/real-time/{symbol}")
        except requests.HTTPError:
            payload = None

        if isinstance(payload, dict):
            rate_value = _parse_float(payload.get("close")) or _parse_float(payload.get("price"))
            if rate_value is not None:
                fx_timestamp_utc = _parse_timestamp(payload.get("timestamp"))
                if fx_timestamp_utc is None:
                    fx_date = _parse_date(payload.get("date"))
                    if fx_date is not None:
                        fx_timestamp_utc = datetime.combine(fx_date, datetime.min.time(), tzinfo=timezone.utc)
                return rate_value, fx_timestamp_utc

        try:
            eod_rows = self._fetch_recent_eod_rows(symbol, limit=1)
        except requests.HTTPError:
            eod_rows = []
        if not eod_rows:
            return None

        rate_value = _parse_float(eod_rows[0].get("close"))
        if rate_value is None:
            return None
        fx_date = _parse_date(eod_rows[0].get("date"))
        fx_timestamp_utc = (
            datetime.combine(fx_date, datetime.min.time(), tzinfo=timezone.utc)
            if fx_date is not None
            else None
        )
        return rate_value, fx_timestamp_utc

    def _get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        request_params: dict[str, Any] = {
            "api_token": self.api_key,
            "fmt": "json",
        }
        if params:
            request_params.update(params)

        response = self.session.get(
            f"{self.base_url}{path}",
            params=request_params,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return response.json()


def _pick_previous_close(rows: list[dict[str, Any]], latest_date: date | None) -> float | None:
    if not rows:
        return None
    if len(rows) == 1:
        return None
    first_date = _parse_date(rows[0].get("date"))
    if latest_date is not None and first_date == latest_date:
        return _parse_float(rows[1].get("close"))
    return _parse_float(rows[0].get("close"))


def _parse_date(value: object) -> date | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _parse_timestamp(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(int(float(value)), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _parse_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
