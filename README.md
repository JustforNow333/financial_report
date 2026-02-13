# Yahoo Finance Lite (US-Only) + Industry Labeling + Next.js UI

Full-stack MVP that:

- Ingests **full US market snapshots** into SQLAlchemy models.
- Computes movers from your own DB (`pct_change` vs previous close).
- AI-labels industries for symbols (`industry_label`, `industry_confidence`, `industry_source`, `industry_updated_at`).
- Serves movers overall or filtered by industry.
- Provides a Next.js frontend with industry selector and gainers/losers tables.

## Stack

- Backend: Python 3.11+, Flask, SQLAlchemy 2, Alembic
- DB: SQLite (local), PostgreSQL (prod)
- Frontend: Next.js + React + SWR
- Provider: Polygon full-market snapshot endpoint (adapter-based, swappable)

## Repo Layout

- `app/`
  - `__init__.py` Flask app factory
  - `config.py` env settings
  - `db.py` engine/session
  - `models.py` Symbol/Snapshot ORM models
  - `providers/` market provider interface + Polygon adapter
  - `ingest.py` ingestion logic + CLI scheduler
  - `industry_taxonomy.py` controlled industry vocabulary
  - `industry_labeler.py` AI+heuristic label inference
  - `label_industries.py` labeling CLI
  - `routes.py` API endpoints
- `migrations/` Alembic files
- `frontend/` Next.js UI
- `tests/` backend tests

## Environment Variables

Use `.env.example` as base:

```bash
cp .env.example .env
```

Key vars:

- `DATABASE_URL` (default `sqlite:///fin_daily_report.db`)
- `POLYGON_API_KEY`
- `MOVER_FILTER_ENABLED` (default `true`)
- `MIN_LAST_PRICE` (default `1.0`)
- `MIN_DAY_VOLUME` (default `100000`)
- `OPENAI_API_KEY` (optional but recommended for higher-quality labels)
- `INDUSTRY_LLM_ENABLED` (default `true`)
- `OPENAI_MODEL` (default `gpt-4o-mini`)
- `NEXT_PUBLIC_API_BASE_URL` for frontend

## Backend Setup (SQLite local)

1. Create venv + install deps:

```bash
python3 -m venv --without-pip .venv
curl -sS https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py
.venv/bin/python /tmp/get-pip.py
.venv/bin/pip install -r requirements.txt
```

2. Run migrations:

```bash
.venv/bin/alembic upgrade head
```

3. Run API:

```bash
.venv/bin/flask --app 'app:create_app' run --host 0.0.0.0 --port 8000
```

## PostgreSQL Setup

Set `.env`:

```bash
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/fin_daily_report
```

Then:

```bash
.venv/bin/alembic upgrade head
```

## Ingestion

One run:

```bash
.venv/bin/python -m app.ingest --once
```

Continuous polling:

```bash
.venv/bin/python -m app.ingest --interval-minutes 5
```

Cron-friendly every 5 minutes:

```cron
*/5 * * * * cd /path/to/fin_daily_report && /path/to/fin_daily_report/.venv/bin/python -m app.ingest --once >> /var/log/fin_daily_ingest.log 2>&1
```

## Industry Labeling (AI)

Label symbols in batches (idempotent by default):

```bash
.venv/bin/python -m app.label_industries --batch-size 200 --max 2000 --force false
```

Notes:

- Default behavior labels only symbols with `industry_label IS NULL`.
- `--force true` relabels all symbols.
- Label source is stored as `industry_source="ai"`.
- If LLM call fails or key is missing, heuristic fallback still assigns labels automatically.

## API Endpoints

- `GET /api/industries`
  - Distinct labels + `All`, plus `Unlabeled` when null labels exist.
- `GET /api/movers/latest?industry=<label|Unlabeled>`
  - Top 10 gainers/losers for latest snapshot.
  - Applies query-time filters: `MIN_LAST_PRICE`, `MIN_DAY_VOLUME` when enabled.
- `GET /api/snapshots/latest?limit=50&sort=pct_change_desc|pct_change_asc`
- `GET /api/symbols/search?q=`

### Example: `/api/industries`

```json
{
  "industries": ["All", "Banks", "Software", "Unlabeled"]
}
```

### Example: `/api/movers/latest?industry=Software`

```json
{
  "asof_ts": "2026-02-13T15:35:00+00:00",
  "industry": "Software",
  "gainers": [
    {
      "rank": 1,
      "ticker": "ABC",
      "name": "ABC Software Inc.",
      "industry_label": "Software",
      "last_price": 12.5,
      "prev_close": 10.0,
      "pct_change": 25.0,
      "volume": 450000
    }
  ],
  "losers": [
    {
      "rank": 1,
      "ticker": "XYZ",
      "name": "XYZ Systems",
      "industry_label": "Software",
      "last_price": 7.2,
      "prev_close": 9.0,
      "pct_change": -20.0,
      "volume": 820000
    }
  ]
}
```

## Frontend (Next.js)

1. Install deps:

```bash
cd frontend
npm install
```

2. Configure API URL:

```bash
cp .env.local.example .env.local
# edit if backend is not on http://localhost:8000
```

3. Run dev server:

```bash
npm run dev
```

Open `http://localhost:3000`.

UI behavior:

- Default industry: `All`
- Industry selector refetches `/api/movers/latest` with `industry` query param
- Shows "Last updated" in America/New_York timezone
- Displays rank, ticker, company, last price, % change, volume

## Tests

```bash
.venv/bin/pytest -q
```

Current test coverage includes:

- `pct_change` computation
- latest movers query ordering/filtering/industry behavior
- industry labeling heuristics + idempotent labeling flow
