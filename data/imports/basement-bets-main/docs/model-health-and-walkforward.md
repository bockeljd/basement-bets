# Model Health & Walk-Forward Evaluation

## Overview
To trust our betting models, we must continuously evaluate their performance on out-of-sample data. This document outlines the system for daily walk-forward evaluation and automated health reporting.

## Daily Evaluation Job (`src/jobs/daily_eval.py`)

### Trigger
- **Schedule**: Daily at 9:00 AM ET (after games settle).
- **Scope**: Evaluate all predictions for games that ended yesterday.

### Workflow
1.  **Fetch Completed Predictions**: Select predictions from `model_predictions` where `game_date` = Yesterday and `result` is known (not Pending).
2.  **Compute Metrics**:
    *   **Brier Score**: Mean squared difference between probability and outcome (0 or 1).
    *   **Log Loss**: Negative log likelihood.
    *   **Calibration Error (ECE)**: Bin predictions (0-0.1, 0.1-0.2, ...) and compare mean predicted prob vs. observed frequency.
    *   **ROI**: Profit/Loss if we had bet flat 1u on all "Actionable" bets.
3.  **Persist**: Store aggregate metrics in `model_health_daily`.
4.  **Check Gates**: Compare 7-day trailing average vs. baselines.

## Database Schema

### `model_health_daily`
| Column | Type | Description |
|---|---|---|
| `id` | UUID | PK |
| `model_version` | TEXT | FK to `model_versions.id` |
| `date` | DATE | Evaluation date |
| `sample_size` | INT | Number of games evaluated |
| `n_actionable` | INT | Number of bets flagged as actionable |
| `brier_score` | FLOAT | Lower is better |
| `log_loss` | FLOAT | Lower is better |
| `roi_actionable` | FLOAT | ROI on actionable bets |
| `ece` | FLOAT | Expected Calibration Error |
| `is_degrading_7d` | BOOLEAN | True if 7d avg error > 21d avg error + threshold |
| `penalty_factor` | FLOAT | calculated penalty (0.0 to 1.0) to dampen future stakes |
| `notes` | TEXT | |

## Automated Summary Generator
A text-based summary for the Admin Dashboard:

> **Model Health Report [2026-01-14]**
> *   **Status**: 🟢 HEALTHY / 🔴 DEGRADING
> *   **7d ROI**: +5.2% (Actionable)
> *   **Calibration**: Slightly overconfident on heavy favorites (>80%).
> *   **Top Regression**: Away Underdogs in Big 12 are underperforming model expectation by 12%.

## Implementation Steps
1.  Create `model_health_daily` table.
2.  Implement `ModelEvaluator` class in `src/analytics/model_evaluator.py`.
3.  Create Cron Endpoint `POST /api/cron/evaluate-models`.
4.  Add Logic to compute specific gates (`is_degrading`).
