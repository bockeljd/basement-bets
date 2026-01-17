# MVP Model Specification

This document defines the baseline analytical models for "Basement Bets".

## 1. Core Model Archetypes

### Moneyline (Win Probability)
- **Model**: Logistic Regression Baseline.
- **Formula**: $P(\text{Home}) = \sigma(\beta_0 + \beta_1 \cdot \Delta\text{Rating} + \beta_2 \cdot \text{HFA})$
- **Inputs**: 
    - `team_ratings`: Elo or Efficiency-based ratings.
    - `hfa`: Home Field Advantage constant (sport-specific).
- **Audit Field**: `inputs_used: {"rating_diff": 4.5, "hfa": 2.1}`.

### Spread (Cover Probability)
- **Model**: Gaussian Linear Transformation.
- **Logic**: 
    - `Fair Spread` = $f(\Delta\text{Rating} + \text{HFA})$.
    - `Cover Prob` = Cumulative Distribution Function (CDF) of $N(\text{Fair Spread}, \sigma^2)$ at the Market Line.
- **Inputs**: 
    - `market_line`: The spread offered by the sportsbook.
    - `std_dev`: Historical spread variance (e.g., ~13.5 for NFL).

### Total (Total Points/Goals)
- **Model**: Poisson (or Skellam) Distribution.
- **Formula**: Independent goals calculated via $P(X=k; \lambda)$.
- **Inputs**:
    - `expected_pace`: Projected number of possessions/opportunities.
    - `efficiency_metrics`: Off/Def efficiency ratings.
- **Logic**: $P(\text{Over } T) = 1 - \sum_{i=0}^{T} P(\text{Home}=i) \otimes P(\text{Away}=j \text{ where } i+j \le T)$.

## 2. Feature Events (Adjustments)

"Feature Events" are discrete, auditable modifiers applied to the baseline.
- **Schema**: `{ "type": "ADJUSTMENT", "target": "total", "delta": -2.5, "reason": "Star Player X Out" }`.
- **Logic**: Modifiers are additive to the baseline model parameters ($\lambda$ or $\mu$).
- **Lifecycle**: Feature Events are stored as an array in `metadata`, allowing users to see *why* a model deviated from pure historical stats.

## 3. Reliability & Versioning
- **Version Pattern**: `YYYY-MM-DD-vX` (e.g., `2024-01-14-v1`).
- **Deterministic**: Given the same `inputs_used` and `feature_events`, the model MUST produce the same `probability`.
- **Inference Latency**: Target < 50ms per game to support real-time edge detection in the UI.
