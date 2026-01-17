# Odds Ingestion Contract

This document defines the requirements for a credit-efficient, auditable ingestion of market data from The Odds API.

## 1. Adapter Interface

### `fetchOdds(sport, markets, regions, date_range)`
- **Input**:
    - `sport`: The Odds API sport key (e.g., `basketball_ncaab`).
    - `markets`: List of market keys (e.g., `h2h`, `spreads`, `totals`).
    - `regions`: Target regions (default `us`).
- **Output**: A normalized list of `odds_snapshots`.
- **Logic**:
    - Must perform **Local Cache Check** before hitting the API.
    - Must standardizes provider team names using `data/team_mapping.json`.

## 2. Credit Efficiency & Caching

| Rule | Implementation |
| :--- | :--- |
| **TTL Caching** | Snapshots for the same event/market are cached for **X minutes** (configurable per sport). |
| **Early vs. Near-Lock** | Higher frequency ingestion (e.g., every 15m) for games starting within 2 hours; lower frequency (e.g., every 4h) for future games. |
| **Credit Budget** | Limit total daily credits used. Stop ingestion if budget is exceeded. |

## 3. Data Normalization Mapping

- **Provider IDs**: Map `event_id` from The Odds API to the internal `games` table via:
    - `commence_time` (overlap within 1 hour)
    - `home_team` / `away_team` (fuzzy/mapping match)
- **Market Enums**:
    - `h2h` -> `ML`
    - `spreads` -> `SPREAD`
    - `totals` -> `TOTAL`

## 4. Rate Limiting & Backoff
- **Concurrency**: Maximum 2 simultaneous ingestion jobs.
- **Failures**: Implement exponential backoff (starting at 5s) for `429 Too Many Requests` or `5xx` errors.

## 5. Acceptance Criteria

- [ ] Ingesting the same sport twice within 1 minute results in only **one** external API call (cached).
- [ ] Ingestion logs correctly report `credits_used` based on the `x-requests-used` header from The Odds API.
- [ ] Mapped event names match the historical `games` table records.
- [ ] `MockOddsAPI` test suite passes with simulated 10-game response.
