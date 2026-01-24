
# Basement Bets

A personal sports betting tracker and analysis platform.

## Setup

### Environment
1.  Copy `.env.template` to `.env`.
2.  Populate `POSTGRES_URL` (or `DATABASE_URL`).
3.  Populate `BASEMENT_PASSWORD` for admin access.

### Database
This project uses **Postgres** (Neon / Vercel Postgres recommended). SQLite is no longer supported for runtime.

**Initialize Schema:**
```bash
./run.sh
# Then call:
curl -X POST http://localhost:8000/api/admin/init-db
```
*Note: This is non-destructive. Returns success if tables exist.*

**Migration (Optional)**
If you have data in a legacy `data/bets.db` SQLite file:
```bash
python3 scripts/migrate_sqlite_to_postgres.py
```

### Running Locally
```bash
./run.sh
```
Starts Backend (FastAPI: 8000) and Frontend (Vite: 5173).

## Developer Notes

**Reset Database:**
To wipe all data and start fresh:
1.  Set `BASEMENT_DB_RESET=1` in `.env`.
2.  Restart server or run init script.
3.  Remove the variable immediately.

**Smoke Test:**
```bash
python3 scripts/db_smoke_test.py
```
