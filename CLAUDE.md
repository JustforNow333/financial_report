# CLAUDE.md

## Project Overview

Full-stack US market movers app: ingests EOD US equities close data via Polygon grouped daily bars, computes daily returns, AI-labels industries, serves via Flask API + Next.js frontend.

## Stack

- **Backend:** Python 3.11+, Flask, SQLAlchemy 2, Alembic
- **Database:** SQLite (local), PostgreSQL (prod)
- **Frontend:** Next.js 15 + React 18 + SWR (in `frontend/`)
- **Market Data:** Polygon grouped daily bars (`StocksClient.get_grouped_daily_bars`)
- **Industry Labeling:** Google Gemini API (AI) + keyword heuristics fallback

## Repo Layout

- `app/` — Flask backend (app factory in `__init__.py`)
- `app/__main__.py` — Direct `python -m app` entry point
- `app/config.py` — `Settings` dataclass loaded from env vars
- `app/db.py` — SQLAlchemy engine + scoped session management
- `app/models.py` — ORM models: `Symbol`, `Ticker`, `Company`, `Snapshot`, `PriceDaily`, `DailyReturn`, `DailyBar`, `IngestRun`, `IngestBaseline`
- `app/routes.py` — API endpoints (`/api/movers/latest`, `/api/industries`, `/api/snapshots/latest`, `/api/symbols/search`, `/api/status`)
- `app/providers/` — Market data provider interface/adapters (`polygon`, `fmp`)
- `app/ingest.py` — Legacy Polygon EOD ingestion (writes to `prices_daily` + `daily_returns`)
- `app/industry_labeler.py` — AI (Gemini) + heuristic industry labeling
- `app/industry_taxonomy.py` — Controlled industry vocabulary + keyword rules
- `app/label_industries.py` — Industry labeling CLI
- `scripts/` — Operational scripts:
  - `scripts/ingest_us_eod_snapshot.py` — **Primary ingest**: Polygon grouped bars → `daily_bars` table
  - `scripts/update_ticker_company_map.py` — Fetch SEC ticker/company mapping → `tickers` table
  - `scripts/seed_tickers_from_sec_file.py` — Seed `tickers` from SEC CSV with SIC codes
  - `scripts/build_sec_company_industry_file.py` — Build SEC company/industry CSV+JSON from EDGAR
- `migrations/` — Alembic migration files
- `frontend/` — Next.js UI
- `tests/` — Backend pytest tests

## Data Flow

1. **Ticker setup:** `scripts/update_ticker_company_map.py` fetches SEC tickers → `tickers` table
2. **SIC enrichment:** `scripts/build_sec_company_industry_file.py` → CSV, then `scripts/seed_tickers_from_sec_file.py` → `tickers.sic_code`/`sic_description`
3. **Daily ingest:** `scripts/ingest_us_eod_snapshot.py` → `daily_bars` table (filters to SEC-mapped common equities)
4. **API routes** query `daily_bars` joined with `tickers`, `symbols`, `companies` for industry labels
5. **Industry labeling:** `python -m app.label_industries` labels `symbols` rows via AI/heuristic

## Common Commands

```bash
# Run backend
flask --app 'app:create_app' run --host 0.0.0.0 --port 8000

# Run migrations
alembic upgrade head

# Run tests
pytest -q

# Update SEC ticker map (run first before ingest)
python scripts/update_ticker_company_map.py

# Build SEC industry file (optional, enriches SIC codes)
python scripts/build_sec_company_industry_file.py
python scripts/seed_tickers_from_sec_file.py

# Ingest market data (primary path — writes to daily_bars)
python scripts/ingest_us_eod_snapshot.py
python scripts/ingest_us_eod_snapshot.py --asof-date 2026-02-14

# Legacy ingest (writes to prices_daily + daily_returns, NOT used by current API routes)
python -m app.ingest --once

# Label industries
python -m app.label_industries --batch-size 200 --max 2000

# Frontend dev server
cd frontend && npm run dev
```

## Testing

- Tests live in `tests/` and use pytest
- `pytest.ini` sets `pythonpath = .`
- Run with `pytest -q` from the project root
- No `conftest.py` — each test creates its own DB session/app

## Environment Variables

Key vars (set in `.env`, see `.env.example`):
- `DATABASE_URL` — default `sqlite:///fin_daily_report.db`
- `POLYGON_API_KEY` — required for Polygon grouped daily bars
- `GEMINI_API_KEY` — for AI industry labeling (optional, falls back to heuristics)
- `INDUSTRY_LLM_ENABLED` — default `true`
- `GEMINI_MODEL` — default `gemini-3-flash`
- `MOVER_FILTER_ENABLED`, `MIN_LAST_PRICE`, `MIN_DAY_VOLUME` — query-time quality filters
- `NEXT_PUBLIC_API_BASE_URL` — frontend API target (default `http://localhost:8000`)
- `SEC_USER_AGENT` — required for SEC EDGAR scripts (format: `AppName email@example.com`)
- `FMP_API_KEY` — for FMP provider (alternative to Polygon)

## Conventions

- Backend follows Flask app factory pattern (`app:create_app`)
- SQLAlchemy 2.x style (mapped_column, DeclarativeBase)
- Alembic for all schema changes — never modify tables manually
- API routes prefixed with `/api/`
- Frontend fetches from `NEXT_PUBLIC_API_BASE_URL`
- **API routes query `daily_bars` table** (not `daily_returns` or `prices_daily`)
- Movers queries exclude outliers (`abs(pct_change) > 0.80`) by default
- Primary ingest is `scripts/ingest_us_eod_snapshot.py` which writes to `daily_bars`
- Ingest pipeline uses exactly two Polygon grouped-bars calls (as-of + previous session)
- Previous trading day is computed offline via local NYSE calendar (no extra Polygon endpoints)
- Preserve free-tier safety: at most 5 req/min; enforce request spacing/backoff on retries
- Industry labeling distinguishes AI vs heuristic source
- Industry labels resolved via: `Company.industry` > `Symbol.industry_label` > `Ticker.sic_description`
