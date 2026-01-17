# Ensemble Model Weight Distribution

## Updated Weights (Total = 100%)

| Source | Weight | Notes |
|--------|--------|-------|
| **BartTorvik** | 30% | Free API, daily efficiency ratings |
| **Existing Model** | 22% | Tempo/efficiency Monte Carlo (reduced from 25%) |
| **ESPN Injuries** | 13% | Player availability impact (reduced from 20%) |
| **Season Stats** | 10% | Current W/L, PPG, recent form (NEW) |
| **Referee Data** | 10% | Foul tendencies, pace impact |
| **Market Signals** | 10% | Line movement (already tracked) |
| **KenPom** | 5% | If available (subscription required) |

**Total**: 100%

## Rationale

- **BartTorvik** (30%): Highest weight - free, reliable, daily updates
- **Existing Model** (22%): Proven Monte Carlo simulation
- **ESPN Injuries** (13%): Important but not always complete
- **Season Stats** (10%): Captures current form and momentum
- **Referee/Market** (10% each): Situational factors
- **KenPom** (5%): Optional premium data source

## Season Stats to Include

1. **Win/Loss Record** (overall and last 10 games)
2. **Points Per Game** (offensive output)
3. **Points Allowed** (defensive strength)
4. **Recent Form** (last 5 games trend)
5. **Home/Away Splits**
6. **Conference Record**

## Implementation

```python
weights = {
    'barttorvik': 0.30,
    'base_model': 0.22,
    'espn_injury': 0.13,
    'season_stats': 0.10,
    'referee': 0.10,
    'market_signals': 0.10,
    'kenpom': 0.05  # Optional
}
```
