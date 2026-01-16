# LLM Slip Parser Contract

This document defines the interface and storage rules for the LLM-based betting slip parser.

## 1. Input Requirements
- **Raw Text**: The unmodified string pasted by the user.
- **Sportsbook ID**: `DK` (DraftKings) or `FD` (FanDuel).
- **User/Account ID**: For multi-tenant isolation.

## 2. Output Schema (`BetSlipParsed`)

```json
{
  "parser_version": "2024-01-14v1",
  "sportsbook": "DraftKings",
  "placed_at": "2024-01-14T12:00:00Z",
  "stake": 50.00,
  "price": {
    "american": -110,
    "decimal": 1.91
  },
  "market_type": "SPREAD",
  "selection": "Kansas Jayhawks",
  "line": -4.5,
  "event_name": "Kansas Jayhawks vs Iowa State Cyclones",
  "sport": "basketball_ncaab",
  "legs": [
    {
       "selection": "Kansas Jayhawks",
       "line": -4.5,
       "price": -110,
       "event": "Kansas Jayhawks vs Iowa State Cyclones"
    }
  ],
  "confidence": 0.95,
  "missing_fields": [],
  "is_parlay": false
}
```

## 3. Storage & Audit Rules

| Field | Requirement |
| :--- | :--- |
| `raw_slip_text` | Store as Immutable blob in `evidence_items`. |
| `raw_slip_hash` | SHA-256 of raw text for primary deduplication. |
| `parsed_json` | Store result in `ingestion_logs` or a dedicated metadata column in `bets`. |
| `parser_version` | Must be stored to allow re-parsing if prompt logic improves. |

## 4. Safety Guardrails

- **Confidence Threshold**: Any slip with `confidence < 0.9` OR `len(missing_fields) > 0` requires **User Review** in the Preview Panel.
- **Critical Fields**: If `stake`, `price`, or `selection` are missing, the `Confirm & Save` button is disabled until manually corrected.
- **Ambiguity**: If the LLM returns multiple possible events, the parser must return the top match and list the others in an `alternatives` array for user selection.
