# ModelOps & Versioning

## Overview
To enable iterative improvements without breaking production stability, we implement distinct model versioning. Every prediction must be traceable to a specific configuration snapshot.

## Database Schema

### `model_versions`
| Column | Type | Description |
|---|---|---|
| `version_id` | TEXT | PK (e.g., 'v1.0.0', 'experimental-xg-v2') |
| `created_at` | TIMESTAMP | |
| `status` | TEXT | 'active', 'experimental', 'retired', 'shadow' |
| `config_json` | JSONB | Full hyperparameters (feature weights, regressors, lookback windows) |
| `description` | TEXT | Human readable intent (e.g., "Added rebounding % to feature set") |

### Updates to `model_predictions`
- Add `model_version_id` (FK to `model_versions`).

## Workflow

### 1. Prediction Generation
When `generate_predictions()` is called:
- It can accept an optional `version_id`.
- If None, it defaults to the single version marked `status='active'`.
- It loads the parameters from `config_json` of that version.
- It stamps the generated rows with that `version_id`.

### 2. Comparison Evaluator
A tool to compare two versions over a common date range.

`compare_versions(v_baseline, v_challenger, start_date, end_date)` returns:
- Delta Brier: `Brier(challenger) - Brier(baseline)` (Negative is good)
- Delta ROI: ROI difference on same set of games.
- Feature Importance Diff: (Optional)

### 3. Promotion Workflow
To promote `experimental` -> `active`:
- **Requirement 1**: Minimum 300 evaluations (games).
- **Requirement 2**: Delta Brier < 0 (Improvement).
- **Requirement 3**: Delta ROI >= 0% (No financial regression).

## Implementation Steps
1.  Create `model_versions` table.
2.  Seed 'v1.0.0' as current active implementation.
3.  Refactor `PredictionEngine` to load config from DB/Object instead of hardcoded constants.
4.  Implement `ModelVersionManager` class.
