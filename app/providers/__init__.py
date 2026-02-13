from __future__ import annotations

from app.config import Settings

from .base import MarketSnapshotProvider
from .polygon import PolygonSnapshotProvider


def get_provider(settings: Settings) -> MarketSnapshotProvider:
    if settings.market_provider == "polygon":
        return PolygonSnapshotProvider(
            api_key=settings.polygon_api_key or "",
            base_url=settings.polygon_base_url,
            timeout_seconds=settings.request_timeout_seconds,
        )

    raise ValueError(f"Unsupported market provider: {settings.market_provider}")
