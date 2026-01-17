# NCAAM Model Improvement Analysis

## Problem
Backtest results show **inverse correlation** between edge size and win rate:
- Edge >= 1.0 pts: 50.0% WR
- Edge >= 3.0 pts: 45.5% WR  
- Edge >= 4.0 pts: 42.9% WR

**This is backwards!** Higher edges should have higher win rates.

## Root Causes

### 1. Edge Calculation May Be Overconfident
The model calculates edge as `abs(model_spread - market_spread)`, but this doesn't account for:
- **Uncertainty in model predictions** (no confidence intervals)
- **Market efficiency** (sharp books already price in most information)
- **Sample size** (365 teams, but limited game data)

### 2. Potential Issues

**A. Model Overfit to Efficiency Ratings**
- Using raw BartTorvik efficiency ratings without adjustments
- Not accounting for recent form, injuries, or lineup changes
- Tempo/efficiency may not translate 1:1 to spreads

**B. Devigging Assumptions**
- Assumes standard vig (-110/-110)
- Doesn't account for sharp vs soft lines
- May be overestimating true probability

**C. No Regression to Mean**
- Large edges might indicate model error, not opportunity
- Should shrink extreme predictions toward market consensus

## Proposed Improvements

### Short-term Fixes

1. **Add Confidence Penalty**
```python
# Reduce edge for extreme deviations
if abs(model_spread - market_spread) > 5.0:
    edge = edge * 0.7  # 30% haircut for suspicious edges
```

2. **Market Respect Factor**
```python
# Blend model with market (70/30 split for large deviations)
if abs(diff) > 3.0:
    adjusted_spread = model_spread * 0.7 + market_spread * 0.3
```

3. **Recalibrate Edge Thresholds**
- Current: 1.5 pts minimum
- Suggested: 0.5-1.0 pts (model may be underestimating small edges)

### Medium-term Improvements

1. **Add Uncertainty Bands**
- Calculate standard error for predictions
- Only bet when market is outside 1-sigma confidence interval

2. **Incorporate Market Signals**
- Line movement (already partially implemented)
- Steam moves (sharp money indicators)
- Closing line value tracking

3. **Style Matchup Adjustments**
- Tempo differential impact
- Offensive/defensive efficiency mismatches
- Home court advantage variations

### Long-term Enhancements

1. **Machine Learning Calibration**
- Train on historical results to calibrate edge → win probability
- Use logistic regression to map edge to actual outcomes

2. **Multi-Model Ensemble**
- Combine efficiency-based, regression-based, and market-based models
- Weight by historical accuracy

3. **Live Data Integration**
- Injury reports
- Lineup changes
- Weather (for outdoor sports)

## Immediate Action Plan

1. **Analyze Edge Distribution**
```bash
# Check if large edges correlate with model errors
SELECT edge, result, COUNT(*) 
FROM model_predictions 
WHERE sport='NCAAM' 
GROUP BY edge, result
ORDER BY edge DESC
```

2. **Implement Conservative Scaling**
```python
# In ncaam_model.py, line ~585
edge_raw = abs(model_spread - market_spread)
edge_adjusted = edge_raw * 0.6  # Conservative 40% haircut
```

3. **Test on Next 20 Games**
- Track performance with adjusted edges
- Compare to baseline

## Success Metrics

- Win rate should increase with edge size
- ROI should be positive at edge >= 2.0 pts
- Target: 55%+ win rate on edge >= 3.0 pts
