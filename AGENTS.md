# AGENTS.md

## Project

Full-stack US market movers app.
- Backend: Flask + SQLAlchemy 2 + Alembic
- Frontend: Next.js 15 + React 18 + SWR
- Data: Polygon grouped daily bars (EOD) → `daily_bars` table, optional Gemini-based industry labeling
- International: curated non-U.S. latest-known snapshots via EODHD → `international_snapshots` table
- Ticker metadata: SEC EDGAR company tickers → `tickers` table (with SIC codes)

## Repository Map

- `app/` — Flask backend source (app factory in `__init__.py`)
- `app/models.py` — ORM models: `Symbol`, `Ticker`, `Company`, `Snapshot`, `PriceDaily`, `DailyReturn`, `DailyBar`, `IngestRun`, `IngestBaseline`
- `app/international.py` — Curated international universe loading + snapshot ingest helpers
- `app/international_routes.py` — `/api/international/*` routes
- `app/routes.py` — API endpoints querying `daily_bars` joined with `tickers`/`symbols`/`companies`
- `app/providers/` — Market data provider adapters (`polygon`, `fmp`, `eodhd`)
- `app/ingest.py` — Legacy ingest (writes to `prices_daily` + `daily_returns`, not used by API routes)
- `app/industry_labeler.py` — AI (Gemini) + heuristic industry labeling
- `app/industry_taxonomy.py` — Controlled industry vocabulary + keyword rules
- `data/international_companies.seed.json` — Deterministic curated non-U.S. company universe seed for the international snapshot path
- `scripts/` — Operational scripts:
  - `scripts/ingest_us_eod_snapshot.py` — **Primary ingest**: Polygon → `daily_bars`
  - `scripts/ingest_international_snapshot.py` — Curated non-U.S. latest-known ingest: EODHD → `international_snapshots`
  - `scripts/update_ticker_company_map.py` — SEC tickers → `tickers` table
  - `scripts/seed_tickers_from_sec_file.py` — Seed `tickers` with SIC codes from SEC CSV
  - `scripts/build_sec_company_industry_file.py` — Build SEC company/industry CSV+JSON
- `migrations/` — Alembic migrations
- `frontend/` — Next.js app
  - Main dashboard currently exposes top-level tabs for `US only`, `Both`, and `International`
- `tests/` — Backend pytest tests

## Local Setup

Preferred Python: 3.11+.

Linux/macOS (`.venv`):
1. `python3 -m venv --without-pip .venv`
2. `curl -sS https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py`
3. `.venv/bin/python /tmp/get-pip.py`
4. `.venv/bin/pip install -r requirements.txt`
5. `.venv/bin/alembic upgrade head`

Windows PowerShell (`venv`):
1. `py -3.11 -m venv .\venv`
2. `.\venv\Scripts\Activate.ps1`
3. `python -m pip install -U pip`
4. `python -m pip install -r requirements.txt`
5. `python -m alembic upgrade head`

## Runbook

- Backend API: `.venv/bin/flask --app 'app:create_app' run --host 0.0.0.0 --port 8000` (Linux/macOS) or `python -m flask --app "app:create_app" run --host 0.0.0.0 --port 8000` (Windows)
- Update SEC ticker map (run before first ingest): `python scripts/update_ticker_company_map.py`
- Build SEC industry file (optional SIC enrichment): `python scripts/build_sec_company_industry_file.py` then `python scripts/seed_tickers_from_sec_file.py`
- **Primary ingest** (EOD → `daily_bars`): `python scripts/ingest_us_eod_snapshot.py` or `python scripts/ingest_us_eod_snapshot.py --asof-date YYYY-MM-DD`
- Legacy ingest (→ `prices_daily`/`daily_returns`, not used by API): `python -m app.ingest --once`
- Label industries: `.venv/bin/python -m app.label_industries --batch-size 200 --max 2000 --force false`
- Tests: `.venv/bin/pytest -q` (Linux/macOS) or `python -m pytest -q` (Windows)
- Frontend:
  1. `cd frontend`
  2. `npm install`
  3. `npm run dev`

## Environment

Copy `.env.example` to `.env` and set values as needed.
Important keys:
- `DATABASE_URL`
- `POLYGON_API_KEY`
- `EODHD_API_KEY`
- `EODHD_BASE_URL`
- `INTERNATIONAL_UNIVERSE_PATH`
- `INTERNATIONAL_STALE_AFTER_DAYS`
- `GEMINI_API_KEY` (optional)
- `INDUSTRY_LLM_ENABLED`
- `MOVER_FILTER_ENABLED`
- `MIN_LAST_PRICE`
- `MIN_DAY_VOLUME`
- `NEXT_PUBLIC_API_BASE_URL` (frontend)
- `SEC_USER_AGENT` (required for SEC EDGAR scripts)
- `FMP_API_KEY` (alternative provider)

## Data Flow

1. `scripts/update_ticker_company_map.py` → `tickers` table (SEC company tickers)
2. `scripts/build_sec_company_industry_file.py` + `scripts/seed_tickers_from_sec_file.py` → SIC codes on `tickers`
3. `scripts/ingest_us_eod_snapshot.py` → `daily_bars` table (Polygon grouped bars, filtered to SEC-mapped common equities)
4. API routes query `daily_bars` joined with `tickers`/`symbols`/`companies` for industry labels
5. `scripts/ingest_international_snapshot.py` → `international_snapshots` table (curated non-U.S. latest-known prices + USD conversion + freshness metadata)
6. `python -m app.label_industries` → AI/heuristic labels on `symbols` table

## Change Guidelines

- Use Alembic for schema changes.
- Keep API routes under `/api/`.
- Preserve SQLAlchemy 2.x patterns used in the codebase.
- Add or update tests in `tests/` for backend behavior changes.
- Keep frontend changes scoped to `frontend/` unless API contracts change.
- **API routes query `daily_bars` table** — tests must seed `DailyBar` rows (not `PriceDaily`/`DailyReturn`).
- Primary EOD ingest is `scripts/ingest_us_eod_snapshot.py` writing to `daily_bars`.
- Use exactly two Polygon calls per normal run: grouped bars for as-of date and previous trading day.
- Previous trading day must be resolved offline via local NYSE market calendar (no API holiday/session calls).
- Primary ingest must fail closed on empty as-of Polygon results; do not delete existing `daily_bars` for that date when the upstream payload is empty.
- Keep mover queries sourced from `daily_bars`, excluding outliers (`abs(pct_change) > 0.80`) by default.
- Industry labels resolved via: `Company.industry` > `Symbol.industry_label` > `Ticker.sic_description`, with blank strings normalized to unlabeled at query time.
- Keep ingest request budget within free tier limits (2 normal calls/run, 5 req/min safe).
- Keep the international snapshot feature additive. Do not force non-U.S. data into the U.S. `daily_bars` model.
- Curated international coverage comes from `data/international_companies.seed.json`; keep the format simple and deterministic.
- Validate seeded international symbols against EODHD exchange symbol lists before ingest. Do not silently shrink the universe when symbols are invalid or exchange validation fails.
- International snapshot semantics are latest-known, not synchronized global real-time. Preserve per-row freshness metadata (`as_of_date`, timestamps, status).
- For EODHD FX conversion, prefer direct `CCYUSD.FOREX` pairs and only invert `CCY.FOREX` when direct USD pairs are unavailable.
- Keep `/api/international/status` and ingest summary output useful for debugging: seeded count, validated count, ingested count, invalid symbols, corrected symbols, failed fetches, missing FX, and stale quotes.
- The frontend international view currently shows top-level tabs for `US only`, `Both`, and `International`, plus top 10 international winners and losers sourced from `/api/international/movers/latest`.

## Validation Checklist

Before submitting changes:
1. Run tests: `./.venv/bin/pytest -q` (Linux/macOS) or `python -m pytest -q` (Windows)
   If you are in WSL against a Windows venv, use `venv/Scripts/python.exe -m pytest -q`.
2. If schema changed, run `./.venv/bin/alembic upgrade head`
3. Validate ingest path: `python scripts/ingest_us_eod_snapshot.py` and `GET /api/status`
4. Validate international ingest path: `python scripts/ingest_international_snapshot.py` and `GET /api/international/status`
5. If frontend changed, run `cd frontend && npm run build` (or at least `npm run dev` smoke test)
