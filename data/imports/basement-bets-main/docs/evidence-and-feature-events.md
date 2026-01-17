# Evidence and Feature Events

This document defines the storage and schema for qualitative evidence (e.g., news, injury reports) and the extracted feature events used for model adjustments.

## 1. Evidence Storage (`evidence_items`)

Qualitative evidence is stored in the `evidence_items` table (shared with bet slips).

| Field | Requirement |
| :--- | :--- |
| `raw_content` | The unmodified text pasted from Action Network or other sources. |
| `content_hash` | SHA-256 for deduplication. |
| `source` | e.g., 'ActionNetwork-News', 'Twitter-Injury'. |
| `metadata` | JSONB containing the extracted `FeatureEvent[]`. |

## 2. Feature Event Schema (`FeatureEvent`)

A `FeatureEvent` is a structured signal extracted from the raw evidence.

```json
{
  "feature_type": "injury | lineup | pace | weather | travel | coaching | market_note",
  "entity": "text (Team or Player name)",
  "normalized_entity": "text (Standardized name from team_mapping.json)",
  "direction": "positive | negative | neutral",
  "magnitude_hint": "low | medium | high",
  "confidence": "float (0.0 - 1.0)",
  "raw_snippet": "text (The original sentence providing this signal)",
  "is_confirmed": "boolean (Requires user check if low confidence)"
}
```

## 3. Audit & Integration Rules

1. **Immutable Evidence**: Once pasted and hashed, the `raw_content` is immutable.
2. **Feature Review**: Extracted features are stored in a `Pending` state if `confidence < 0.85`. Users must review and "Confirm" the feature before it is injected into model simulations.
3. **No Auto-Bet**: This module strictly provides **inputs** for models. It never generates bet recommendations independently.
4. **Linkage**: Every prediction that uses a feature adjustment MUST link back to the `evidence_id` in its `metadata.feature_events` array.

## 4. Feature Types Definitions

- **injury**: Player health/availability.
- **lineup**: Starting roster changes.
- **pace**: Notes on tempo, rest, or game flow.
- **weather**: Wind, rain, temperature impacts.
- **travel**: Back-to-back games, altitude, travel distance.
- **coaching**: Strategy changes, suspensions, or "hot seat" status.
- **market_note**: Information about sharp money or significant line moves mentioned in text.
