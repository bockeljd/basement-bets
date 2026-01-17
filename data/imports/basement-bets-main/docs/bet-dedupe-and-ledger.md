# Bet Deduplication & Ledger Integrity

This document defines the rules for ensuring manual bet logging is auditable, idempotent, and free from double-counting.

## 1. Deduplication Strategy

### Primary: `raw_slip_hash`
- **Logic**: SHA-256 hash of the cleaned `raw_slip_text`.
- **Constraint**: Unique per (`user_id`, `raw_slip_hash`).
- **Effect**: If the exact same text is pasted twice, the second attempt is rejected immediately.

### Secondary: `near-duplicate` Key
- **Logic**: A composite fingerprint to catch slips that might have slight text variations but represent the same event.
- **Fingerprint**: `(sportsbook, placed_at ± 5m, stake, price, selection_normalized)`
- **Behavior**:
  - If a match is found, the system flags it as a "Possible Duplicate" in the UI.
  - User must explicitly click "Save Anyway" to override.

## 2. Ledger & Audit Trails

### Bet Legs
- To support parlays, every one `bet` row has 1-N `bet_legs`.
- **settlement**: Always linked back to the `bet_id`.

### Audit Log Entries
Every significant state change must be recorded in `ingestion_logs` or a `history` table:

| Action | Metadata Stored |
| :--- | :--- |
| **CREATE** | `evidence_id`, `parser_version`, `raw_text`, `user_id` |
| **SETTLE** | `result` (Won/Loss), `settled_at`, `source_id` (e.g., Odds API Event ID) |
| **OVERRIDE** | `reason`, `old_value`, `new_value`, `admin_id` |

## 3. API Error Specs

| Code | Message | HTTP Status |
| :--- | :--- | :--- |
| `ERR_DUPE_RAW` | "This slip has already been uploaded." | 409 Conflict |
| `WARN_DUPE_NEAR` | "Possible duplicate detected." | 200 OK (with `warning` flag) |
| `ERR_INVALID_LEDGER` | "Stake must be greater than zero." | 400 Bad Request |

## 4. Acceptance Criteria

- [ ] Pasting the same DraftKings text twice results in an `ERR_DUPE_RAW`.
- [ ] Changing a single character in a slip but keeping the same Stake/Time/Selection triggers `WARN_DUPE_NEAR`.
- [ ] Every bet successfully saved has a valid `evidence_id` pointing to the raw text.
- [ ] Ledger summary (Profit/Loss) always matches the sum of settled bets.
