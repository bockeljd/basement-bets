# NCAAM BartTorvik Daily Ingestion

## Overview
This document outlines the architecture for a daily scheduled job to ingest BartTorvik team metrics into `bt_team_metrics_daily`. This ensures we have a historical record of team strength metrics (AdiOE, AdjDE, etc.) for backtesting and analysis.

## Architecture

### 1. Scheduler
- **Trigger**: Vercel Cron
- **Schedule**: Daily at 6:30 AM ET (`30 11 * * *` UTC)
- **Endpoint**: `GET /api/cron/ingest-barttorvik`

### 2. Job Workflow (`src/jobs/ingest_barttorvik.py`)
1. **Validation**: Check `CRON_SECRET` header (implicit Vercel security).
2. **Context**: Determine `season` (e.g., 2026) and `snapshot_date` (Today's Date: YYYY-MM-DD).
3. **Idempotency Check**: Query `provider_ingestion_runs` or `bt_raw_artifacts`. If `snapshot_date` exists and status is `SUCCESS`, skip unless `force=true`.
4. **Fetch**:
   - URL: `https://barttorvik.com/{year}_team_results.json` (This returns CURRENT stats, effectively a snapshot if fetched daily).
   - *Note*: If we need true "timemachine" for past dates *retrospectively*, we'd use `trank.php?date=...`, but for *daily* forward-fill, `_team_results.json` is the canonical current snapshot.
   - **User Reqt Note**: "Fetch the timemachine snapshot...". If `team_results.json` is just the current state, saving it daily *creates* the timemachine.
5. **Store Raw**:
   - Save JSON content to `data/raw/barttorvik/{date}_team_results.json.gz` (or Supabase Storage).
   - Record metadata in `bt_raw_artifacts`.
6. **Process**:
   - Parse JSON.
   - Map Team Name -> `team_id` using `data/team_mapping.json`.
   - Insert/Upsert into `bt_team_metrics_daily`.
   - Quarantine failures to `bt_ingestion_quarantine`.
7. **Log**: Update `provider_ingestion_runs` with outcome.

### 3. Data Schema

#### `bt_raw_artifacts`
| Column | Type | Description |
|---|---|---|
| id | UUID | PK |
| source | TEXT | 'barttorvik' |
| snapshot_date | DATE | The logical date of the data |
| fetched_at | TIMESTAMP | When it was downloaded |
| storage_path | TEXT | Path in storage bucket or FS |
| content_hash | TEXT | SHA256 of raw content for integity |
| status | TEXT | 'STORED', 'PROCESSED', 'FAILED' |

#### `bt_team_metrics_daily`
| Column | Type | Description |
|---|---|---|
| id | SERIAL/UUID | PK |
| team_id | UUID/TEXT | Canonical Team ID (FK? or just consistent string) |
| date | DATE | Snapshot date |
| season | INTEGER | e.g. 2026 |
| adj_oe | FLOAT | Adjusted Offensive Efficiency |
| adj_de | FLOAT | Adjusted Defensive Efficiency |
| barthag | FLOAT | Power Rating |
| tempo | FLOAT | Adjusted Tempo |
| rank | INTEGER | T-Rank |
| ... | ... | Other metrics |
| created_at | TIMESTAMP | |
| UNIQUE(team_id, date) | | |

#### `provider_ingestion_runs`
| Column | Type | Description |
|---|---|---|
| id | UUID | PK |
| provider | TEXT | 'barttorvik' |
| run_at | TIMESTAMP | |
| status | TEXT | 'SUCCESS', 'FAILURE' |
| rows_processed | INT | |
| error_log | JSONB | |

## Implementation Plan
1. **Database**: Add tables in `src/database.py`.
2. **Service**: Extend `BartTorvikClient` in `src/services/barttorvik.py` with `fetch_and_store_snapshot`.
3. **Job**: Create `src/api.py` endpoint.
4. **Config**: Update `vercel.json`.
