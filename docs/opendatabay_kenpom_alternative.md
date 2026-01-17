# Free KenPom Alternative: Opendatabay

## Source
**Opendatabay NCAA Division 1 Basketball Efficiency Metrics**
- URL: https://opendatabay.com/dataset/ncaa-division-1-basketball-efficiency-metrics
- **Cost**: Free (CSV download)
- **Coverage**: NCAA Division 1 (all teams)
- **Metrics**: Offensive Efficiency, Defensive Efficiency, Adjusted Tempo, Strength of Schedule
- **Update Frequency**: Annual (covers 2024 season)

## Metrics Included

Similar to KenPom:
- **AdjO** (Adjusted Offensive Efficiency)
- **AdjD** (Adjusted Defensive Efficiency)  
- **AdjT** (Adjusted Tempo)
- **AdjEM** (Adjusted Efficiency Margin) = AdjO - AdjD
- **SOS** (Strength of Schedule)

## Implementation Plan

### 1. Download and Ingest Data
```bash
# Download CSV from Opendatabay
curl -o data/opendatabay_ncaa_efficiency.csv \
  https://opendatabay.com/dataset/ncaa-division-1-basketball-efficiency-metrics/download

# Ingest into database
python3 scripts/ingest_opendatabay_efficiency.py
```

### 2. Database Schema
```sql
CREATE TABLE efficiency_ratings (
    team_name TEXT PRIMARY KEY,
    adj_o REAL,          -- Adjusted Offensive Efficiency
    adj_d REAL,          -- Adjusted Defensive Efficiency
    adj_t REAL,          -- Adjusted Tempo
    adj_em REAL,         -- Efficiency Margin (AdjO - AdjD)
    sos REAL,            -- Strength of Schedule
    source TEXT DEFAULT 'opendatabay',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 3. Integration into Ensemble
```python
# src/services/opendatabay_client.py
class OpendatabayClient:
    def get_team_efficiency(self, team_name: str) -> Dict:
        # Query efficiency_ratings table
        return {
            'adj_o': 110.5,
            'adj_d': 95.3,
            'adj_em': 15.2,
            'adj_t': 68.5
        }
```

## Comparison to KenPom

| Feature | KenPom | Opendatabay |
|---------|--------|-------------|
| Cost | $20/year | Free |
| Update Frequency | Daily | Annual |
| API Access | Yes (paid) | No (CSV only) |
| Metrics | Full suite | Core metrics |
| Accuracy | Gold standard | Similar methodology |

## Limitations

1. **Annual Updates**: Data is updated once per season (not daily like KenPom)
2. **No API**: Must download CSV and ingest manually
3. **Historical Only**: May not have current season data immediately

## Workaround for Current Season

Use **BartTorvik** (free, daily updates) as primary source and **Opendatabay** as validation/backup:
- Primary: BartTorvik (already integrated)
- Backup: Opendatabay (for historical comparison)
- Ensemble: Weight BartTorvik higher (30%) vs Opendatabay (20%)

## Conclusion

**Recommendation**: Use BartTorvik as "KenPom alternative" since:
1. ✅ Free API access
2. ✅ Daily updates
3. ✅ Already integrated
4. ✅ Similar methodology to KenPom

Opendatabay can serve as historical validation dataset.
