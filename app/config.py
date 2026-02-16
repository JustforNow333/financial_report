from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "t", "yes", "y", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str
    market_data_provider: str
    market_provider: str
    fmp_api_key: str | None
    fmp_base_url: str
    eod_ingest_hour_et: int
    polygon_api_key: str | None
    polygon_base_url: str
    request_timeout_seconds: float
    mover_filter_enabled: bool
    min_last_price: float
    min_day_volume: int
    movers_limit: int
    ingest_interval_minutes: int
    industry_llm_enabled: bool
    gemini_api_key: str | None
    gemini_base_url: str
    gemini_model: str

    @classmethod
    def from_env(cls) -> "Settings":
        mover_filter_enabled = _get_bool(
            "MOVER_FILTER_ENABLED",
            _get_bool("QUALITY_FILTER_ENABLED", True),
        )
        market_data_provider = os.getenv(
            "MARKET_DATA_PROVIDER",
            os.getenv("MARKET_PROVIDER", "polygon"),
        ).strip().lower()
        return cls(
            database_url=os.getenv("DATABASE_URL", "sqlite:///fin_daily_report.db"),
            market_data_provider=market_data_provider,
            market_provider=market_data_provider,
            fmp_api_key=os.getenv("FMP_API_KEY"),
            fmp_base_url=os.getenv("FMP_BASE_URL", "https://financialmodelingprep.com").rstrip("/"),
            eod_ingest_hour_et=int(os.getenv("EOD_INGEST_HOUR_ET", "18")),
            polygon_api_key=os.getenv("POLYGON_API_KEY"),
            polygon_base_url=os.getenv("POLYGON_BASE_URL", "https://api.polygon.io").rstrip("/"),
            request_timeout_seconds=float(os.getenv("REQUEST_TIMEOUT_SECONDS", "30")),
            mover_filter_enabled=mover_filter_enabled,
            min_last_price=float(os.getenv("MIN_LAST_PRICE", "1.0")),
            min_day_volume=int(os.getenv("MIN_DAY_VOLUME", "100000")),
            movers_limit=int(os.getenv("MOVERS_LIMIT", "10")),
            ingest_interval_minutes=int(os.getenv("INGEST_INTERVAL_MINUTES", "5")),
            industry_llm_enabled=_get_bool("INDUSTRY_LLM_ENABLED", True),
            gemini_api_key=os.getenv("GEMINI_API_KEY"),
            gemini_base_url=os.getenv(
                "GEMINI_BASE_URL",
                "https://generativelanguage.googleapis.com/v1beta",
            ).rstrip("/"),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-3-flash"),
        )

    def as_flask_config(self) -> dict[str, object]:
        return {
            "DATABASE_URL": self.database_url,
            "MARKET_PROVIDER": self.market_data_provider,
            "MARKET_DATA_PROVIDER": self.market_data_provider,
            "EOD_INGEST_HOUR_ET": self.eod_ingest_hour_et,
            "MOVERS_LIMIT": self.movers_limit,
            "MOVER_FILTER_ENABLED": self.mover_filter_enabled,
            "MIN_LAST_PRICE": self.min_last_price,
            "MIN_DAY_VOLUME": self.min_day_volume,
        }
