from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import get_session, init_engine, remove_session
from app.industry_labeler import IndustryLabeler, SymbolForLabeling
from app.models import Symbol

logger = logging.getLogger(__name__)


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "t", "yes", "y", "on"}


def label_industries(
    *,
    batch_size: int,
    max_symbols: int | None,
    force: bool,
    settings: Settings | None = None,
    session: Session | None = None,
) -> dict[str, int]:
    local_settings = settings or Settings.from_env()
    labeler = IndustryLabeler(local_settings)

    owns_session = session is None
    if session is None:
        session = get_session()

    labeled_count = 0
    processed_count = 0
    unlabeled_count = 0
    last_id = 0

    try:
        while True:
            remaining = None
            if max_symbols is not None:
                remaining = max_symbols - processed_count
                if remaining <= 0:
                    break

            limit = min(batch_size, remaining) if remaining is not None else batch_size

            stmt = select(Symbol).where(Symbol.id > last_id).order_by(Symbol.id.asc()).limit(limit)
            if not force:
                stmt = stmt.where(
                    Symbol.industry_label.is_(None),
                    Symbol.industry_updated_at.is_(None),
                )

            symbols = session.execute(stmt).scalars().all()
            if not symbols:
                break

            now_utc = datetime.now(timezone.utc)
            inputs = [
                SymbolForLabeling(symbol_id=symbol.id, ticker=symbol.ticker, name=symbol.name)
                for symbol in symbols
            ]
            predictions = labeler.label_batch(inputs)

            for symbol in symbols:
                prediction = predictions.get(symbol.id)
                if prediction is None:
                    continue

                symbol.industry_label = prediction.label
                symbol.industry_confidence = prediction.confidence
                symbol.industry_source = "ai"
                symbol.industry_updated_at = now_utc

                if prediction.label is None:
                    unlabeled_count += 1
                else:
                    labeled_count += 1

            processed_count += len(symbols)
            last_id = symbols[-1].id
            session.commit()

            logger.info(
                "Industry labeling progress: processed=%s labeled=%s unlabeled=%s",
                processed_count,
                labeled_count,
                unlabeled_count,
            )

        summary = {
            "processed": processed_count,
            "labeled": labeled_count,
            "unlabeled": unlabeled_count,
        }
        logger.info("Industry labeling complete: %s", summary)
        return summary
    except Exception:
        session.rollback()
        logger.exception("Industry labeling failed")
        raise
    finally:
        if owns_session:
            remove_session()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Label symbol industries")
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument("--max", dest="max_symbols", type=int, default=None)
    parser.add_argument("--force", type=str, default="false")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    args = _parse_args()
    settings = Settings.from_env()
    init_engine(settings.database_url)

    force = _parse_bool(args.force)
    batch_size = max(1, args.batch_size)
    max_symbols = args.max_symbols
    if max_symbols is not None and max_symbols <= 0:
        max_symbols = None

    label_industries(
        batch_size=batch_size,
        max_symbols=max_symbols,
        force=force,
        settings=settings,
    )


if __name__ == "__main__":
    main()
