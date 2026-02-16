from __future__ import annotations

from datetime import date

from app.providers.fmp import FmpEodBulkProvider


class _MockResponse:
    def __init__(self, payload, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise Exception(f"http {self.status_code}")

    def json(self):
        return self._payload


def test_fetch_eod_bulk_parses_valid_rows(monkeypatch) -> None:
    payload = [
        {
            "symbol": "AAA",
            "date": "2026-02-14",
            "open": 9.0,
            "high": 10.0,
            "low": 8.0,
            "close": 10.0,
            "adjClose": 10.0,
            "volume": 1000,
            "name": "AAA Corp",
            "exchange": "NYSE",
        }
    ]

    def _mock_get(url, params, timeout):
        assert url.endswith("/stable/eod-bulk")
        assert params["date"] == "2026-02-14"
        return _MockResponse(payload)

    monkeypatch.setattr("app.providers.fmp.requests.get", _mock_get)

    provider = FmpEodBulkProvider(api_key="k", base_url="https://financialmodelingprep.com")
    rows = provider.fetch_eod_bulk(date(2026, 2, 14))

    assert len(rows) == 1
    assert rows[0].symbol == "AAA"
    assert rows[0].close == 10.0
    assert rows[0].volume == 1000.0


def test_fetch_eod_bulk_skips_rows_missing_required_fields(monkeypatch) -> None:
    payload = [
        {"symbol": "", "date": "2026-02-14", "close": 10.0},
        {"symbol": "AAA", "date": "2026-02-14", "close": None},
        {"symbol": "BBB", "date": "2026-02-14", "close": 11.0},
    ]

    def _mock_get(url, params, timeout):
        return _MockResponse(payload)

    monkeypatch.setattr("app.providers.fmp.requests.get", _mock_get)

    provider = FmpEodBulkProvider(api_key="k", base_url="https://financialmodelingprep.com")
    rows = provider.fetch_eod_bulk(date(2026, 2, 14))

    assert [row.symbol for row in rows] == ["BBB"]
