
# Odds Adapter Contract

## Overview
The Odds Adapter system provides a standardized way to ingest, normalize, and store odds snapshots from multiple providers (Odds API, Action Network, etc.) into a canonical `odds_snapshots` table.

## Data Schema
Any provider adapter must produce a list of dictionaries with the following canonical fields:

| Field | Type | Description |
|---|---|---|
| `event_id` | TEXT | Canonical event UUID from `events` |
| `book` | TEXT | Key of the sportsbook (e.g., 'draftkings', 'fanduel') |
| `market_type` | TEXT | Normalized market: `MONEYLINE`, `SPREAD`, `TOTAL` |
| `side` | TEXT | Normalized side: `HOME`, `AWAY`, `OVER`, `UNDER`, `DRAW` |
| `line` | REAL | Point spread or total line (nullable for ML) |
| `price` | REAL | American odds or decimal price |
| `captured_at` | TIMESTAMP | Precise time of ingestion |
| `captured_bucket` | TIMESTAMP | Trimmed to 15-minute intervals for idempotency |

## Normalization Rules
1. **Market Type**: Must be one of `MONEYLINE`, `SPREAD`, `TOTAL`. Avoid lowercase or variants like `ML`.
2. **Side**: Use `HOME`/`AWAY` for team-based markets instead of team names. Use `OVER`/`UNDER` for totals.
3. **Idempotency**: The `odds_snapshots` table enforces a uniqueness constraint on `(event_id, market_type, side, line, book, captured_bucket)`. This prevents duplicate snapshots within the same 15-minute window for the same price/line.

## Usage
### Ingestion
```python
from src.services.odds_adapter import OddsAdapter
adapter = OddsAdapter()
adapter.normalize_and_store(raw_payload, provider="odds_api")
```

### Retrieval
```python
from src.database import get_last_prestart_snapshot
snapshots = get_last_prestart_snapshot(event_id, "SPREAD")
```
