# EV and Policy Engine

This document defines the rules for converting model probabilities and market odds into disciplined betting recommendations.

## 1. Odds Processing

### De-vigging (Fair Probability)
- **Method**: Multiplicative (Proportional) de-vig as a baseline.
- **Formula**: $P_{\text{fair}} = \frac{P_{\text{implied}}}{\sum P_{\text{implied}}}$
- **Input**: Two-way or Three-way market odds.

### Edge & Expected Value (EV)
- **Edge**: `model_prob` - `fair_prob`
- **EV per $100**: $((\text{model_prob} \cdot \text{payout}) - (1 - \text{model_prob}) \cdot \text{stake}) \cdot \frac{100}{\text{stake}}$

## 2. Recommendation Policy (Gating)

A prediction is only "Recommended" if it passes all gates:

| Gate | Threshold | Reason |
| :--- | :--- | :--- |
| **Edge** | > 2.0% | Minimum statistical advantage required. |
| **EV** | > 3.5% | Minimum return on capital required. |
| **Confidence** | > 0.70 | Minimum model certainty required. |
| **Max Odds** | +500 (6.00) | Prevent "long-shot bias" and high-variance tails. |

## 3. Position Sizing (Kelly Criterion)

### Fractional Kelly
- **Baseline**: 0.25x Kelly (Quarter-Kelly) for conservative bankroll growth.
- **Formula**: $f^* = \text{fraction} \cdot \frac{p \cdot b - q}{b}$
  - $p$: model prob, $q$: 1-p, $b$: decimal odds - 1.

### Risk Caps
- **Single Bet Cap**: Max 2% of total bankroll.
- **Daily Exposure**: Max 10% of total bankroll in pending bets.
- **Correlation Throttle**: If multiple bets share a same-game `group_id`, reduce sizing by 50% for secondary bets.

## 4. Decision Explanation (Metadata)

Every recommendation includes a `decision` object:
```json
{
  "recommendation": "Recommended",
  "sizing": {
    "units": 1.2,
    "percent_bankroll": 0.6,
    "strategy": "0.25x Kelly"
  },
  "gates": {
    "edge_ok": true,
    "ev_ok": true,
    "confidence_ok": true
  },
  "explanation": "High edge (4.5%) in a low-spread NBA game. Adjusted for 0.8 uncertainty proxy."
}
```
"Excluded" bets will list the failed gate (e.g., `"explanation": "Excluded: Edge (1.1%) below threshold (2.0%)"`).
