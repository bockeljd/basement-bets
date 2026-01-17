# Performance Analytics Dashboard (V1)

## Overview
The Performance Dashboard provides advanced financial and betting metrics beyond the basic summary. It focuses on growth, risk-adjusted returns, and drawdowns.

## Key Metrics
- **ROI (Return on Investment)**: (Total Profit / Total Wagered) * 100.
- **Yield**: Same as ROI, often used in soccer/EPL.
- **Maximum Drawdown**: The largest peak-to-trough decline in bankroll (percentage and absolute).
- **Sharpe Ratio (Adjusted)**: Risk-adjusted return calculation based on win consistency.
- **Profit by Sport/Market**: Stacked area charts showing growth over time.

## UI Components
1. **Equity Curve Chart**: A LineChart showing cumulative profit over time.
2. **Drawdown Chart**: An area chart showing the underwater periods.
3. **Metric Cards**:
   - Best Win (by $ and %)
   - Longest Win/Loss Streak
   - Average Odds taken
   - Average EV of bets placed (vs Closing Line)

## Backend Requirements
- `AnalyticsEngine` needs a `get_time_series_profit()` method.
- `AnalyticsEngine` needs a `get_drawdown_metrics()` method.

## Settlement Flow
- Manual toggle in the History view to mark a bet as WON, LOST, or PUSH.
- This should trigger an immediate ledger update and re-cache of analytics.
