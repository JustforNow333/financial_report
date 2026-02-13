from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class SnapshotQuote:
    ticker: str
    name: str | None
    exchange: str | None
    last_price: float | None
    prev_close: float | None
    day_open: float | None
    day_high: float | None
    day_low: float | None
    day_volume: int | None


class MarketSnapshotProvider(ABC):
    @abstractmethod
    def fetch_snapshot(self, asof_ts: datetime) -> list[SnapshotQuote]:
        raise NotImplementedError
