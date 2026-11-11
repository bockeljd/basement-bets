import datetime
from typing import Any, Dict, Optional, Tuple

from src.agents.base import BaseAgent
from src.database import get_db_connection, _exec


class DataQualityAgent(BaseAgent):
    """Pre-flight checks to ensure we are not skipping games due to missing data.

    This agent is intentionally pragmatic:
    - Detects stale/missing odds snapshots for today's slate
    - Detects stale/missing Torvik team metrics (bt_team_metrics_daily)
    - Optionally triggers ingestion if configured

    Returns a dict:
      {
        status: 'ok'|'degraded'|'blocked',
        checks: {...},
        actions_taken: [...],
        actions_recommended: [...]
      }
    """

    def execute(self, context: Dict[str, Any], *args, **kwargs) -> Dict[str, Any]:
        league = str(context.get('league') or 'NCAAM').upper()
        date_et = context.get('date_et')

        # Thresholds (env-overridable)
        odds_fresh_minutes = int(context.get('odds_fresh_minutes') or 90)
        min_odds_snapshots = int(context.get('min_odds_snapshots') or 200)
        min_events_today = int(context.get('min_events_today') or 10)

        trigger_ingestion = bool(context.get('trigger_ingestion') or False)

        checks: Dict[str, Any] = {}
        actions_taken = []
        actions_recommended = []

        with get_db_connection() as conn:
            if not date_et:
                date_et = _exec(conn, "SELECT (NOW() AT TIME ZONE 'America/New_York')::date::text").fetchone()[0]

            # --- Events (today ET) ---
            ev_cnt = _exec(conn, """
                SELECT COUNT(*) AS n
                FROM events
                WHERE league=%s AND DATE(start_time AT TIME ZONE 'America/New_York')=%s
            """, (league, date_et)).fetchone()
            events_today = int((ev_cnt.get('n') if isinstance(ev_cnt, dict) else ev_cnt[0]) or 0)
            checks['events_today'] = events_today

            if events_today < min_events_today:
                actions_recommended.append(f"Ingest events for {league} (low events_today={events_today})")

            # --- Odds freshness ---
            snap = _exec(conn, """
                SELECT COUNT(*) AS n,
                       MAX(captured_at) AS last_captured
                FROM odds_snapshots os
                JOIN events e ON e.id=os.event_id
                WHERE e.league=%s
                  AND DATE(e.start_time AT TIME ZONE 'America/New_York')=%s
                  AND os.captured_at >= NOW() - (%s || ' minutes')::interval
            """, (league, date_et, odds_fresh_minutes)).fetchone()

            odds_recent = int((snap.get('n') if isinstance(snap, dict) else snap[0]) or 0)
            last_cap = snap.get('last_captured') if isinstance(snap, dict) else (snap[1] if len(snap) > 1 else None)
            checks['odds_recent_snapshots'] = odds_recent
            checks['odds_last_captured_at'] = str(last_cap) if last_cap is not None else None
            checks['odds_fresh_minutes'] = odds_fresh_minutes

        if odds_recent < min_odds_snapshots:
            actions_recommended.append(
                f"Ingest odds snapshots for {league} (recent={odds_recent} < min={min_odds_snapshots}, window={odds_fresh_minutes}m)"
            )
            if trigger_ingestion:
                try:
                    # Trigger odds ingestion in-process
                    from src.services.odds_fetcher_service import OddsFetcherService
                    from src.services.odds_adapter import OddsAdapter

                    date_yyyymmdd = datetime.datetime.now().strftime('%Y%m%d')
                    fetcher = OddsFetcherService()
                    adapter = OddsAdapter()
                    raw_games = fetcher.fetch_odds(league, start_date=date_yyyymmdd)
                    adapter.normalize_and_store(raw_games, league=league, provider='action_network')
                    actions_taken.append('ingest_odds')
                except Exception as e:
                    actions_recommended.append(f"Odds ingest failed: {e}")

        # --- Torvik metrics freshness (bt_team_metrics_daily) ---
        try:
            with get_db_connection() as conn:
                r = _exec(conn, "SELECT MAX(date) AS max_date, COUNT(*) AS n FROM bt_team_metrics_daily").fetchone()
                max_date = r.get('max_date') if isinstance(r, dict) else r[0]
                n = int((r.get('n') if isinstance(r, dict) else r[1]) or 0)
                checks['bt_team_metrics_rows'] = n
                checks['bt_team_metrics_max_date'] = str(max_date) if max_date is not None else None

            # We treat max_date < today as stale.
            stale = False
            try:
                if max_date is None:
                    stale = True
                else:
                    today = datetime.date.today()
                    if hasattr(max_date, 'date'):
                        max_d = max_date.date()  # type: ignore
                    else:
                        max_d = max_date
                    stale = (str(max_d) < str(today))
            except Exception:
                stale = True

            if stale:
                actions_recommended.append('Ingest Torvik team metrics (bt_team_metrics_daily is stale)')
                if trigger_ingestion:
                    try:
                        from src.services.barttorvik import BartTorvikClient
                        from src.database import init_bt_team_metrics_db

                        init_bt_team_metrics_db()
                        client = BartTorvikClient()
                        client.get_efficiency_ratings()
                        actions_taken.append('ingest_torvik')
                    except Exception as e:
                        actions_recommended.append(f"Torvik ingest failed: {e}")
        except Exception as e:
            actions_recommended.append(f"Torvik freshness check failed: {e}")

        # Determine status
        status = 'ok'
        if actions_recommended:
            status = 'degraded'
        if trigger_ingestion and any('failed' in a.lower() for a in actions_recommended):
            status = 'degraded'

        return {
            'status': status,
            'date_et': date_et,
            'league': league,
            'checks': checks,
            'actions_taken': actions_taken,
            'actions_recommended': actions_recommended,
        }
