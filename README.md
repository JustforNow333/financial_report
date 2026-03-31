# Market Movers + International Snapshots

## What To Do Now

1. Update your local `.env` so `INTERNATIONAL_UNIVERSE_PATH` is `data/international_companies.seed.json`, or remove that override entirely.
2. Set your provider keys in `.env`, especially `POLYGON_API_KEY` and `EODHD_API_KEY`.
3. Apply migrations if needed:

```bash
venv/Scripts/python.exe -m alembic upgrade head
```

4. Run the U.S. ingest:

```bash
python scripts/ingest_us_eod_snapshot.py
```

5. Run the international ingest:

```bash
python scripts/ingest_international_snapshot.py
```

6. Start the backend:

```bash
venv/Scripts/python.exe -m flask --app "app:create_app" run --host 0.0.0.0 --port 8000
```

7. Start the frontend:

```bash
cd frontend
npm install
npm run dev
```

8. Open `http://localhost:3000` and use the `US only`, `Both`, and `International` tabs.

Current manual-review items for your EODHD setup:

- `ROG.SW` needs review; EODHD returned `RO.SW` and `ROP.SW` for Roche.
- All 10 Japan `.TSE` seed symbols currently fail on your EODHD setup and need provider-supported symbol mapping or a different source.

Full-stack personal project for:

- U.S. market movers from Polygon grouped daily bars written to `daily_bars`
- industry-aware Flask APIs backed by SQLAlchemy
- a Next.js frontend for the U.S. movers view
- a separate curated non-U.S. “latest known USD-normalized snapshot” pipeline backed by EODHD

## Stack

- Backend: Python 3.11+, Flask, SQLAlchemy 2, Alembic
- DB: SQLite locally, PostgreSQL in production
- Frontend: Next.js 15, React 18, SWR
- U.S. provider: Polygon grouped daily bars
- International provider: EODHD

## Repo Layout

- `app/`
  - `__init__.py` Flask app factory
  - `config.py` environment-backed settings
  - `db.py` engine/session handling
  - `models.py` ORM models, including `daily_bars` and `international_snapshots`
  - `international.py` curated-universe loading, international snapshot helpers, and ingest logic
  - `routes.py` U.S. API routes
  - `international_routes.py` additive `/api/international/*` routes
  - `providers/` provider adapters, including Polygon, FMP, and EODHD
- `scripts/`
  - `ingest_us_eod_snapshot.py` primary U.S. EOD ingest into `daily_bars`
  - `ingest_international_snapshot.py` curated non-U.S. latest-known snapshot ingest
  - `update_ticker_company_map.py`, `build_sec_company_industry_file.py`, `seed_tickers_from_sec_file.py`
- `data/`
  - `international_companies.seed.json` authoritative curated non-U.S. universe seed
- `migrations/`
- `frontend/`
- `tests/`

## Environment Variables

Start from `.env.example`.

Key variables:

- `DATABASE_URL`
- `POLYGON_API_KEY`
- `EODHD_API_KEY`
- `EODHD_BASE_URL` default: `https://eodhd.com`
- `INTERNATIONAL_UNIVERSE_PATH` default: `data/international_companies.seed.json`
- `INTERNATIONAL_STALE_AFTER_DAYS` default: `3`
- `SEC_USER_AGENT`
- `REQUEST_TIMEOUT_SECONDS`
- `MOVER_FILTER_ENABLED`
- `MIN_LAST_PRICE`
- `MIN_DAY_VOLUME`
- `GEMINI_API_KEY` optional
- `INDUSTRY_LLM_ENABLED`
- `NEXT_PUBLIC_API_BASE_URL`

## Local Setup

Linux/macOS:

```bash
python3 -m venv --without-pip .venv
curl -sS https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py
.venv/bin/python /tmp/get-pip.py
.venv/bin/pip install -r requirements.txt
.venv/bin/alembic upgrade head
```

Windows PowerShell:

```powershell
py -3.11 -m venv .\venv
.\venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -r requirements.txt
python -m alembic upgrade head
```

WSL against a Windows venv:

```bash
venv/Scripts/python.exe -m pip install -r requirements.txt
venv/Scripts/python.exe -m alembic upgrade head
```

## Running the Backend

Linux/macOS:

```bash
.venv/bin/flask --app 'app:create_app' run --host 0.0.0.0 --port 8000
```

Windows / WSL with Windows venv:

```bash
venv/Scripts/python.exe -m flask --app "app:create_app" run --host 0.0.0.0 --port 8000
```

## U.S. Pipeline

The U.S. pipeline remains the primary movers flow.

Run the SEC metadata path first:

```bash
python scripts/update_ticker_company_map.py
python scripts/build_sec_company_industry_file.py
python scripts/seed_tickers_from_sec_file.py
```

Run the primary U.S. ingest:

```bash
python scripts/ingest_us_eod_snapshot.py
python scripts/ingest_us_eod_snapshot.py --asof-date YYYY-MM-DD
```

Behavior:

- resolves the current and previous NYSE session offline
- uses Polygon grouped bars
- writes to `daily_bars`
- keeps the U.S. movers APIs sourced from `daily_bars`
- excludes extreme outliers by default in movers queries

## International Snapshot Pipeline

The international feature is intentionally separate from the U.S. EOD movers model.

It is a latest-known snapshot system:

- tracks a deterministic curated list of 100 non-U.S. companies from `data/international_companies.seed.json`
- fetches the latest available non-U.S. price per tracked company from EODHD
- converts local prices to USD using EODHD FX data
- computes `pct_growth = ((local_price / previous_local_close) - 1) * 100` when previous close is available
- stores freshness metadata in `international_snapshots`

This is not a synchronized global market clock. Different markets may have different “latest available” timestamps at the same ingest run.

Validation behavior:

- the seed file is grouped by country and exchange and lives in-repo, so the universe does not depend on dynamic discovery
- before ingest, the app calls EODHD exchange symbol list endpoints per exchange and validates every seeded symbol
- invalid symbols are not silently dropped; they are recorded in ingest status output and exposed through `/api/international/status`
- if a seeded symbol is wrong but the company name matches exactly one symbol on the same exchange, the app applies a deterministic correction and records it in status output
- if validation fails for an exchange, those symbols remain visible as validation failures rather than shrinking the universe quietly
- if an older local `.env` still points `INTERNATIONAL_UNIVERSE_PATH` at `data/international_curated_companies.json`, update or remove that override; the app also includes a legacy-path fallback for that exact old filename

Run the international ingest:

```bash
python scripts/ingest_international_snapshot.py
python scripts/ingest_international_snapshot.py --asof-date YYYY-MM-DD
python scripts/ingest_international_snapshot.py --universe-path path/to/companies.json
```

The ingest is idempotent by `(provider_symbol, as_of_date)` and is designed to keep going when some symbols fail, when FX is missing, or when previous close data is unavailable.

Status/reporting now includes:

- total seeded companies
- total validated companies
- total successfully ingested companies
- invalid symbols
- corrected symbols
- missing FX rates
- stale quotes
- failed fetches
- quote-unavailable symbols

FX conversion notes:

- the provider prefers direct pairs like `EURUSD.FOREX` when available
- if only the inverse-style `EUR.FOREX` quote is available, the app inverts it before computing `usd_price`

## API Endpoints

U.S. endpoints:

- `GET /api/status`
- `GET /api/industries`
- `GET /api/movers/latest`
- `GET /api/snapshots/latest`
- `GET /api/symbols/search`

International endpoints:

- `GET /api/international/status`
- `GET /api/international/snapshots/latest?country=<country>&exchange=<exchange>&limit=<n>`
- `GET /api/international/movers/latest?country=<country>&exchange=<exchange>&limit=<n>`
- `GET /api/international/companies?country=<country>&exchange=<exchange>&limit=<n>&include_inactive=true|false`

Example international snapshot response shape:

```json
{
  "asof_date": "2026-03-20",
  "provider": "eodhd",
  "count": 2,
  "snapshots": [
    {
      "ticker": "ASML.AS",
      "name": "ASML Holding",
      "exchange": "Euronext Amsterdam",
      "country": "Netherlands",
      "currency": "EUR",
      "local_price": 812.4,
      "usd_price": 877.392,
      "prev_close": 799.2,
      "pct_growth": 1.651652,
      "market_cap": null,
      "as_of_date": "2026-03-20",
      "provider": "eodhd",
      "price_timestamp_utc": "2026-03-20T16:30:00+00:00",
      "fx_timestamp_utc": "2026-03-20T18:00:00+00:00",
      "market_status": "fresh"
    }
  ]
}
```

## Frontend

The existing frontend remains focused on the U.S. movers experience.
It now includes top-level dashboard tabs that filter what is shown:

- `US only`
- `Both`
- `International`

Setup:

```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
```

Production build:

```bash
npm run build
```

UI behavior:

- `US only` shows the existing U.S. movers view with the industry selector
- `Both` shows the U.S. movers cards plus the curated international snapshot section
- `International` shows only the curated non-U.S. latest-known snapshot section
- the international section includes top 10 winners, top 10 losers, and the broader curated company snapshot list

## Tests

Linux/macOS:

```bash
.venv/bin/pytest -q
```

Windows / WSL with Windows venv:

```bash
venv/Scripts/python.exe -m pytest -q
```

## Notes

- `international_companies.seed.json` is the deterministic source of truth for the curated non-U.S. universe.
- Some international symbols may be temporarily stale, partially populated, or unavailable depending on provider coverage.
- `market_cap` is nullable because the first implementation treats it as optional provider metadata.
