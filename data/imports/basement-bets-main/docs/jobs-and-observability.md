# Jobs and Observability Specification

This document defines the platform-level requirements for scheduled tasks and system monitoring.

## 1. Scheduled Jobs (Vercel Cron)

Jobs are triggered via authenticated `GET` requests to `/api/jobs/*`.

| Job Name | Path | Schedule | Purpose |
| :--- | :--- | :--- | :--- |
| **Odds Snapshot** | `/api/jobs/odds-snapshot` | `*/15 * * * *` | Fetch latest odds for active sports. |
| **Predictive Run** | `/api/jobs/run-models` | `0 * * * *` | Re-run ML models on fresh odds. |
| **Grading Sync** | `/api/jobs/grade-settlement` | `0 3 * * *` | Sync scores for recently completed games. |

### Protection: Cron Secret
- All `/api/jobs` endpoints must verify the `CRON_SECRET` header (standard Vercel pattern).
- Requests without a valid token return `401 Unauthorized`.

## 2. Ingestion Logs & Error Reporting

All jobs must write to the `ingestion_logs` table:

```json
{
  "job_name": "odds-snapshot",
  "status": "success",
  "summary": {
    "sports": ["basketball_ncaab", "americanfootball_nfl"],
    "snapshots_added": 142,
    "credits_used": 2,
    "execution_time_ms": 1250
  }
}
```

- **Critical Failures** (e.g., Database Down, API 401) should trigger a high-priority entry flagged for notification.
- **Ignored Errors** (e.g., Game postponed) are logged as warnings.

## 3. Data Freshness Dashboard (Observability)

The frontend "Admin" or "System Status" view should show:

| Widget | Logic |
| :--- | :--- |
| **Odds Freshness** | `NOW() - MAX(timestamp)` from `odds_snapshots` per sport. |
| **Model Freshness** | `NOW() - MAX(created_at)` from `model_predictions`. |
| **Settlement Lag** | Count of `Pending` bets where `commence_time < NOW() - 24h`. |
| **Credit Burn** | Monthly sum of `credits_used` vs. `total_budget`. |

## 4. Acceptance Criteria

- [ ] Manual trigger of `/api/jobs/odds-snapshot` returns `401` without `CRON_SECRET`.
- [ ] `/api/health` includes a `jobs` section with `last_run` timestamps.
- [ ] Simulate an API failure (Mock 500) and verify an `ingestion_logs` entry with `status: failure` is created.
- [ ] Dashboard displays 🔴 alert if Odds Freshness > 4h for a primary sport.
