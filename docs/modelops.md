
# Model Operations & Evaluation

## Overview
The Model Ops layer provides versioning, prediction logging, and automated daily evaluation of betting models.

## Architecture

### 1. Model Registry (`model_versions`)
Tracks all models by `sport` and `version_tag`.
- `id`: Unique ID.
- `config_json`: Hyperparameters/features used.
- `lifecycle_status`: experimental, production, archived.

### 2. Prediction Logging (`predictions`)
Models must log probabilistic outputs **before** the event.
- `output_win_prob`: Probability of Home Win / Over / Cover.
- `output_implied_margin`: Projected margin.
- `feature_snapshot_date`: When the prediction was made (to enforce no-lookhead).

### 3. Daily Evaluation
The `EvaluationService` runs daily (or on-demand) to grade predictions against settled outcomes.
Metrics are aggregated by (Date, Model, League, Market) and stored in `model_health_daily`.

#### Metrics Computed
*   **Brier Score**: Mean Squared Error of probabilities. Lower is better.
    - `(prob - outcome)^2`
*   **Log Loss**: Information loss. Lower is better.
    - `- (y log(p) + (1-y) log(1-p))`
*   **Accuracy**: Simple win rate (Threshold > 0.5).

### 4. API & Health Check
*   `GET /api/model/health?date=2024-01-01&league=NFL`
    *   Returns metrics for monitoring.

## Usage
### Logging a Prediction
```python
from src.database import store_prediction_v2
store_prediction_v2({
    "model_version_id": 1,
    "event_id": "evt-123",
    "output_win_prob": 0.55,
    "feature_snapshot_date": datetime.now()
})
```

### Running Evaluation
```python
from src.services.evaluation_service import EvaluationService
svc = EvaluationService()
svc.evaluate_daily_performance() # Defaults to today
```
