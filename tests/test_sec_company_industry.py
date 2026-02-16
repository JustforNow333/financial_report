from __future__ import annotations

import json
from pathlib import Path

from scripts.build_sec_company_industry_file import (
    RateLimiter,
    _extract_sic_fields,
    _format_cik,
    _load_submissions_payload,
)


def test_format_cik_zero_pads_to_10_digits() -> None:
    assert _format_cik(320193) == "0000320193"
    assert _format_cik("789019") == "0000789019"


def test_extract_sic_fields() -> None:
    payload = {"sic": "3571", "sicDescription": "Electronic Computers"}
    sic_code, sic_description = _extract_sic_fields(payload)

    assert sic_code == 3571
    assert sic_description == "Electronic Computers"


def test_load_submissions_payload_uses_fresh_cache_without_network(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cik_padded = "0000320193"
    submissions_dir = tmp_path / "submissions"
    submissions_dir.mkdir(parents=True, exist_ok=True)
    cache_path = submissions_dir / f"CIK{cik_padded}.json"
    expected = {"sic": "3571", "sicDescription": "Electronic Computers"}
    cache_path.write_text(json.dumps(expected), encoding="utf-8")

    monkeypatch.setattr("scripts.build_sec_company_industry_file.SUBMISSIONS_CACHE_DIR", submissions_dir)

    class _Session:
        def __init__(self) -> None:
            self.called = False

        def get(self, *args, **kwargs):  # pragma: no cover - must not be called
            self.called = True
            raise AssertionError("network call should not happen when cache is fresh")

    session = _Session()
    limiter = RateLimiter(max_requests_per_second=2.0)

    payload = _load_submissions_payload(
        session=session,
        limiter=limiter,
        user_agent="TestAgent test@example.com",
        cik_padded=cik_padded,
    )

    assert payload == expected
    assert session.called is False
