from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.industry_labeler import heuristic_prediction
from app.label_industries import label_industries
from app.models import Base, Symbol


def _make_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    return SessionLocal()


def _settings() -> Settings:
    return Settings(
        database_url="sqlite+pysqlite:///:memory:",
        market_provider="polygon",
        polygon_api_key=None,
        polygon_base_url="https://api.polygon.io",
        request_timeout_seconds=10,
        mover_filter_enabled=True,
        min_last_price=1.0,
        min_day_volume=100_000,
        movers_limit=10,
        ingest_interval_minutes=5,
        industry_llm_enabled=False,
        openai_api_key=None,
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4o-mini",
    )


def test_heuristic_prediction_matches_keywords() -> None:
    pred = heuristic_prediction("NVDA", "NVIDIA Corporation")
    assert pred.label == "Other"

    pred2 = heuristic_prediction("INTC", "Intel Semiconductor Manufacturing")
    assert pred2.label == "Semiconductors"
    assert pred2.confidence > 0.5


def test_label_industries_idempotent_without_force() -> None:
    session = _make_session()

    already_labeled = Symbol(
        ticker="ABC",
        name="ABC Bank Holdings",
        exchange="NYSE",
        industry_label="Banks",
        industry_confidence=0.95,
        industry_source="ai",
        industry_updated_at=datetime(2026, 2, 13, tzinfo=timezone.utc),
        active=True,
    )
    unlabeled = Symbol(
        ticker="SEMIX",
        name="Semiconductor Devices Inc",
        exchange="NASDAQ",
        active=True,
    )
    session.add_all([already_labeled, unlabeled])
    session.commit()

    summary = label_industries(
        batch_size=100,
        max_symbols=None,
        force=False,
        settings=_settings(),
        session=session,
    )

    assert summary["processed"] == 1
    assert summary["labeled"] == 1

    refreshed = session.get(Symbol, already_labeled.id)
    assert refreshed is not None
    assert refreshed.industry_label == "Banks"
    assert refreshed.industry_confidence == 0.95

    refreshed_unlabeled = session.get(Symbol, unlabeled.id)
    assert refreshed_unlabeled is not None
    assert refreshed_unlabeled.industry_label == "Semiconductors"
    assert refreshed_unlabeled.industry_source == "ai"
    assert refreshed_unlabeled.industry_updated_at is not None

    second_summary = label_industries(
        batch_size=100,
        max_symbols=None,
        force=False,
        settings=_settings(),
        session=session,
    )
    assert second_summary["processed"] == 0
