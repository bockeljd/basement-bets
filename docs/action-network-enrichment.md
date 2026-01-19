# Action Network Enrichment Discovery

**Date**: 2026-01-18
**Endpoint Audited**: `GET https://api.actionnetwork.com/web/v1/scoreboard/{league}?date={YYYYMMDD}`

## Findings

### 1. Betting Splits (Public/Sharp)
The `odds` array in the game object contains bookmaker objects (e.g., Book ID 15, 69). These objects possess the specific keys for betting percentages and money handles, matching the request requirements.

**Observed Keys:**
- `ml_home_public` / `ml_away_public`
- `ml_home_money` / `ml_away_money`
- `spread_home_public` / `spread_away_public`
- `spread_home_money` / `spread_away_money`
- `total_over_public` / `total_under_public`
- `total_over_money` / `total_under_money`

**Status:**
- **Schema**: CONFIRMED. The keys are present in the JSON.
- **Data**: NULL. In the inspected response, all values were `null`. This indicates the data is supported by the API schema but likely requires a specific permission level or is simply missing for upcoming games in the free tier.
- **Strategy**: Implement `action_splits` table and ingestion logic to map these fields. Logic will gracefully handle `null` values (ingest nothing or skip row).

### 2. Injuries
**Status**: MISSING.
- The `scoreboard` payload contains `teams` objects, but they only contain `id`, `full_name`, `abbr`, `score`, and `standings`.
- No `injuries` array or `roster` data was found.
- **Strategy**: Create `action_injuries` table as requested, but **do not** implement ingestion logic yet. We will not guess at `.../injuries` endpoints.

### 3. Props
**Status**: MISSING (Player Props).
- The `odds` array contains markets for `game`, `firsthalf`, `secondhalf`, `quarters`.
- It does **not** contain Player Props (e.g., "Anytime TD Scorer").
- **Strategy**: Create `action_props` table, but postpone ingestion.

### 4. News
**Status**: MISSING.
- No news content found in `scoreboard`.

## Architecture Plan

### New Tables
1.  **`action_game_enrichment`**: Will store the full `game` JSON object. This is critical because if/when fields like Injuries or Props appear in this feed (or if we switch feeds), we will have the historical data saved.
2.  **`action_splits`**: Will map the explicit keys found above.

### Ingestion Logic (`src/services/action_enrichment_service.py`)
- **Step 1**: Fetch `scoreboard`.
- **Step 2**: Store raw game JSON in `action_game_enrichment` (Fingerprint: `sha256(game_id + updated_at_ts)`).
- **Step 3**: Parse `odds` array. If any `*_public` or `*_money` field is non-null:
    - Insert into `action_splits`.
