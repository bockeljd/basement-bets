# Prediction Schema

This document defines the structured output for all model predictions to ensure auditability and walk-forward verification.

## 1. Schema Definition (`ModelPrediction`)

```json
{
  "game_id": "text (References games table)",
  "sport_key": "text",
  "commence_time": "ISO8601",
  "prediction_type": "ML | SPREAD | TOTAL",
  "selection": "text",
  "line": "numeric (nullable)",
  "model_version": "text (e.g., 2024-01-14-v1)",
  "probability": "float (0.0 - 1.0)",
  "uncertainty_proxy": "float (e.g., variance or confidence interval)",
  "inputs_used": {
    "home_rating": 88.5,
    "away_rating": 82.1,
    "hfa": 2.5,
    "pace": 70.1,
    "std_dev": 13.5
  },
  "feature_events": [
    {
      "type": "ADJUSTMENT",
      "delta": -1.5,
      "reason": "Key player doubtful"
    }
  ],
  "training_window": {
    "start": "2023-11-01",
    "end": "2024-01-13"
  },
  "notes": "text (optional summary)",
  "timestamp": "ISO8601 (Creation time)"
}
```

## 2. Walk-Forward Verification

To support future backtesting, the `training_window` and `inputs_used` are **immutable**.
- **Constraint**: A prediction for a `game_id` must be generated *before* the `commence_time`.
- **Integrity**: Any change to the model logic must iterate the `model_version`.

## 3. Auditable Metadata

| Field | Purpose |
| :--- | :--- |
| `uncertainty_proxy` | Used by the Policy Engine to scale Kelly sizing (Higher uncertainty = Lower fraction). |
| `feature_events` | Decouples pure mathematical logic from human/news adjustments. |
| `inputs_used` | Essential for debugging "Why did the model pick this?" months later. |
