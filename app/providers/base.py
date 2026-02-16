from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date


@dataclass(slots=True)
class EodQuoteRow:
    symbol: str
    date: date
    open: float | None
    high: float | None
    low: float | None
    close: float
    adj_close: float | None
    volume: float | None
    name: str | None = None
    exchange: str | None = None


class MarketDataProvider(ABC):
    @abstractmethod
    def fetch_eod_bulk(self, asof_date: date) -> list[EodQuoteRow]:
        raise NotImplementedError
