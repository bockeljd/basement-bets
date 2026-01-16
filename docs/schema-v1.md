# Database Schema v1 (Postgres + Supabase RLS)

This schema is designed for multi-tenancy, idempotency, and thorough auditability.

## 1. Core Tables

### `profiles`
User metadata and preferences.
- `id`: uuid (PK, references auth.users)
- `email`: text
- `is_premium`: boolean
- `created_at`: timestamptz

### `bankroll_accounts`
Users can have multiple bankroll accounts (e.g., 'Personal', 'Testing').
- `id`: uuid (PK)
- `user_id`: uuid (FK, RLS)
- `name`: text (e.g., 'Main', 'Degen', 'Model-Test')
- `provider_sync`: text (optional, if tied to a specific book API)
- `is_active`: boolean
- `created_at`: timestamptz
- **Constraint**: Unique (`user_id`, `name`)

### `evidence_items`
Raw data source for extraction.
- `id`: uuid (PK)
- `user_id`: uuid (FK, RLS)
- `account_id`: uuid (FK, references bankroll_accounts)
- `raw_content`: text
- `content_hash`: text (Unique for local idempotency: `user_id`, `content_hash`)
- `source`: text (e.g., 'DraftKings-Text', 'FanDuel-CSV')
- `created_at`: timestamptz

### `bets` (Settlement Ledger)
The primary ledger of placed bets.
- `id`: uuid (PK)
- `user_id`: uuid (FK, RLS)
- `account_id`: uuid (FK, references bankroll_accounts)
- `evidence_id`: uuid (FK, references evidence_items)
- `placed_at`: timestamptz
- `description`: text
- `selection`: text
- `stake`: numeric
- `odds_dec`: numeric
- `payout`: numeric
- `status`: text (Pending, Won, Lost, Pushed)
- `raw_slip_hash`: text (Unique for idempotency: `user_id`, `raw_slip_hash`)
- `dedupe_fingerprint`: text (Unique: `user_id`, `account_id`, `description`, `placed_at`, `stake`, `selection`)

### `odds_snapshots`
Time-series of market data.
- `id`: bigserial (PK)
- `event_id`: text
- `sport_key`: text
- `provider`: text
- `bookmaker`: text
- `market`: text
- `selection`: text
- `line`: numeric
- `price`: numeric
- `timestamp`: timestamptz
- `snapshot_bucket`: timestamptz (Used for deduplication / density control)
- **Constraint**: Unique (`event_id`, `market`, `bookmaker`, `selection`, `snapshot_bucket`)

### `ingestion_logs`
- `id`: uuid (PK)
- `user_id`: uuid (FK)
- `job_name`: text
- `status`: text
- `summary`: jsonb (counts, errors)
- `created_at`: timestamptz

## 2. Row Level Security (RLS) Policies

| Table | Policy Name | Access | Check |
| :--- | :--- | :--- | :--- |
| `profiles` | Users can view own profile | SELECT | `auth.uid() = id` |
| `evidence_items` | Users can CRUD own evidence | ALL | `auth.uid() = user_id` |
| `bets` | Users can CRUD own bets | ALL | `auth.uid() = user_id` |
| `odds_snapshots` | Public Read / No Write | SELECT | `true` (Market data is shared) |

## 3. Performance & Audit Rules

1. **Idempotency**: All insertion functions MUST use `ON CONFLICT (...) DO NOTHING` based on the fingerprints defined above.
2. **Audit Loop**: Every row in `bets` MUST link back to an `evidence_id` where available.
3. **Indexes**:
   - `bets`: `idx_bets_user_date` on (`user_id`, `placed_at` DESC)
   - `odds_snapshots`: `idx_odds_event_time` on (`event_id`, `timestamp` DESC)
   - `evidence_items`: `idx_evidence_hash` on (`user_id`, `content_hash`)

## 4. Migration Plan
1. **Baseline**: `20240114_init_schema.sql` (Creates tables + RLS).
2. **Auth Hook**: Trigger to create `profiles` row on Auth Signup.
3. **Incremental**: Add `last_ingested_at` to `profiles` to track health.
