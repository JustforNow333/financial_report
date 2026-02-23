# Migrations

This folder contains Alembic migration history for the backend schema.

## Current Revision Chain

1. `0001_initial`
2. `0002_add_industry_columns`
3. `0003_add_eod_tables`
4. `0004_add_tickers_daily_bars`
5. `0005_add_sic_columns_to_tickers`

## Conventions

- Never edit existing revision files after they are applied in shared environments.
- Add new schema changes as new revision files in `migrations/versions/`.
- Keep upgrade/downgrade logic explicit and reversible where practical.
- Prefer SQLAlchemy/Alembic operations over raw SQL unless necessary.

## Validation

Run after adding a migration:

- `./venv/Scripts/python.exe -m alembic upgrade head`
- `./venv/Scripts/python.exe -m pytest -q`
