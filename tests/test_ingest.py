from app.ingest import compute_pct_change


def test_compute_pct_change_normal_case() -> None:
    result = compute_pct_change(last_price=110.0, prev_close=100.0)
    assert result == 10.0


def test_compute_pct_change_returns_none_for_invalid_prev_close() -> None:
    assert compute_pct_change(last_price=10.0, prev_close=0.0) is None
    assert compute_pct_change(last_price=10.0, prev_close=-1.0) is None
    assert compute_pct_change(last_price=10.0, prev_close=None) is None


def test_compute_pct_change_returns_none_for_missing_last_price() -> None:
    assert compute_pct_change(last_price=None, prev_close=100.0) is None
