from __future__ import annotations

from app.config import Settings

from .base import MarketDataProvider
from .eodhd import EodhdInternationalProvider
from .fmp import FmpEodBulkProvider
from .polygon import PolygonSnapshotProvider


def get_provider(settings: Settings) -> MarketDataProvider:
    provider = settings.market_data_provider
    if provider == "fmp":
        return FmpEodBulkProvider(
            api_key=settings.fmp_api_key or "",
            base_url=settings.fmp_base_url,
            timeout_seconds=settings.request_timeout_seconds,
        )
    if provider == "polygon":
        return PolygonSnapshotProvider(
            api_key=settings.polygon_api_key or "",
            base_url=settings.polygon_base_url,
            timeout_seconds=settings.request_timeout_seconds,
        )

    raise ValueError(f"Unsupported market provider: {provider}")
