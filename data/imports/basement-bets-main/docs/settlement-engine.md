
# Settlement Engine Hardening

## Overview
The Settlement Engine determines the outcome of bets based on game results. It is designed to be **idempotent**, **deterministic**, and **observable**.

## Core Mechanisms

### 1. Idempotency & Fingerprinting
To safely re-run settlement cycles without duplicate entries, every settlement event is fingerprinted using a SHA256 hash of:
*   `event_id`
*   `home_score`, `away_score` (Final Result)
*   `market_type` (e.g., MONEYLINE, SPREAD)
*   `side` (HOME, AWAY, OVER)
*   `line` (if applicable)
*   `grading_version`

**Note:** Timestamps (`updated_at`) and metadata are excluded from the fingerprint. This ensures that metadata updates to a game result do not trigger a regrade unless the *score* changes.

The `settlement_events` table enforces a `UNIQUE` constraint on this fingerprint. The engine uses `INSERT ... ON CONFLICT(fingerprint) DO NOTHING` and checks the row count to detect if an event was actually new.

### 2. Grading Logic
The engine strictly enforces grading requirements:
*   **Moneyline (ML)**: Requires explicit `side` (HOME/AWAY). Inferred logic from text is disabled for strictness.
*   **Spread/Total**: Requires explicit `line` and `side`.
*   **Unsupported Markets**: Markets like `TEAM_TOTAL` (if not implemented) return `UNSETTLED` with a reason code.

### 3. Transaction Safety
Processing occurs in a cycle:
1.  Fetch Candidate Legs (PENDING/UNSETTLED).
2.  For each leg:
    *   Fetch Result.
    *   Grade Leg.
    *   Insert Settlement Event (Idempotent).
    *   Update Leg Status (Atomically committed per leg).
3.  If any leg update fails, that leg is rolled back, but the cycle continues for others.

### 4. Reconciliation API
You can trigger and monitor settlement via the API:
`GET /api/settlement/reconcile?league=NCAAM&limit=100`

Returns stats on:
*   `processed_legs`
*   `inserted_events` (New settlements)
*   `skipped_idempotent` (Already settled with same result)
*   `missing_results` (Game not final yet)

## Schema
### `settlement_events`
| Column | Type | Description |
|os|---|---|
| fingerprint | TEXT UNIQUE | Canonical hash for idempotency |
| event_id | TEXT | FK to events_v2 |
| result | JSON | Snapshot of result used for grading |
| computed | JSON | Calculated margins/totals |
