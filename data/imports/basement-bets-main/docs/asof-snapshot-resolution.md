# BartTorvik As-Of Snapshot Resolution

## Overview
To ensure model predictions are historically accurate and free from look-ahead bias, we must use a deterministic "As-Of" resolver. This system selects the correct historical snapshot of BartTorvik data for any given game time.

## Core Rules

1.  **Primary Rule**: `Target Snapshot Date = DATE(Tipoff Time) - 1 Day`.
    *   *Rationale*: Data for a game played on Jan 14th is best represented by the stats finalized at the end of Jan 13th.
2.  **Fallback Rule**: If the primary snapshot is missing, use the **most recent snapshot strictly before** the Tipoff Time.
    *   *Limit*: Do not fallback more than 7 days (stale data risk).
3.  **Strict Governance**:
    *   If no valid snapshot is found within the window, the prediction generation **MUST FAIL** (Block).
    *   We never use data *from* the game day itself (unless explicitly stamped as "Pre-Game" which T-Rank doesn't strictly guarantee stable intra-day).

## Database Schema Updates

### `model_predictions` Table
We must append audit columns to the prediction table to enforce reproducibility.

| Column | Type | Description |
|---|---|---|
| `data_snapshot_date` | DATE | The file date of the source data used. |
| `data_snapshot_id` | UUID | FK to `bt_raw_artifacts.id` (Traceability). |

## Resolution Logic (Pseudocode)

```python
def resolve_snapshot_date(tipoff_at: datetime) -> date:
    target_date = tipoff_at.date() - timedelta(days=1)
    
    # 1. Check Primary
    if snapshot_exists(target_date):
        return target_date
        
    # 2. Check Fallback (recent past)
    # Find max(date) where date < tipoff_at.date()
    # Limit: must be within last 7 days
    alternative = find_latest_snapshot_before(tipoff_at)
    
    if alternative:
        return alternative
        
    # 3. Fail
    raise DataQualityError(f"No valid snapshot found for game {tipoff_at}")
```

## Acceptance Tests

### Scenario A: Standard Daily Flow
- **Game**: Jan 14, 7:00 PM
- **Available Snapshots**: Jan 12, Jan 13, Jan 14
- **Result**: Select **Jan 13**.
- **Reason**: `Jan 14 - 1 day`.

### Scenario B: Missing Yesterday (Gap)
- **Game**: Jan 14, 7:00 PM
- **Available Snapshots**: Jan 11, Jan 12 (Jan 13 missing)
- **Result**: Select **Jan 12**.
- **Reason**: Most recent strictly before Jan 14.

### Scenario C: Look-Ahead Prevention
- **Game**: Jan 14, 7:00 PM
- **Available Snapshots**: Jan 14 (Morning), Jan 15
- **Result**: **Blocking Error**.
- **Reason**: Jan 14 is same-day (risky), Jan 15 is future. No past data available.

### Scenario D: Stale Data
- **Game**: Jan 20
- **Available Snapshots**: Jan 10
- **Result**: **Blocking Error**.
- **Reason**: Fallback > 7 days old.

## Implementation Steps
1.  Add `resolve_snapshot(game_date)` method to `BartTorvikService`.
2.  Update `generate_prediction` workflow to call resolver first.
3.  Add `data_snapshot_date` column to `model_predictions` schema.
