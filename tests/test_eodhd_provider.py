from __future__ import annotations

from datetime import datetime, timezone

import requests

from app.providers.eodhd import EodhdInternationalProvider


class _MockResponse:
    def __init__(self, payload, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"http {self.status_code}")

    def json(self):
        return self._payload


def test_fetch_fx_rate_to_usd_prefers_direct_pair(monkeypatch) -> None:
    def _mock_get(url, params, timeout):
        if url.endswith("/api/real-time/EURUSD.FOREX"):
            return _MockResponse({"close": 1.08, "timestamp": 1774096800})
        raise AssertionError(f"unexpected url: {url}")

    provider = EodhdInternationalProvider(api_key="k", base_url="https://eodhd.com")
    monkeypatch.setattr(provider.session, "get", _mock_get)

    quote = provider.fetch_fx_rate_to_usd("EUR")

    assert quote is not None
    assert quote.rate_to_usd == 1.08
    assert quote.fx_timestamp_utc == datetime.fromtimestamp(1774096800, tz=timezone.utc)


def test_fetch_fx_rate_to_usd_falls_back_to_inverse_pair(monkeypatch) -> None:
    def _mock_get(url, params, timeout):
        if url.endswith("/api/real-time/GBPUSD.FOREX"):
            return _MockResponse({}, status_code=404)
        if url.endswith("/api/eod/GBPUSD.FOREX"):
            return _MockResponse([], status_code=404)
        if url.endswith("/api/real-time/GBP.FOREX"):
            return _MockResponse({"close": 0.8, "timestamp": 1774096800})
        raise AssertionError(f"unexpected url: {url}")

    provider = EodhdInternationalProvider(api_key="k", base_url="https://eodhd.com")
    monkeypatch.setattr(provider.session, "get", _mock_get)

    quote = provider.fetch_fx_rate_to_usd("GBP")

    assert quote is not None
    assert quote.rate_to_usd == 1.25
    assert quote.fx_timestamp_utc == datetime.fromtimestamp(1774096800, tz=timezone.utc)
