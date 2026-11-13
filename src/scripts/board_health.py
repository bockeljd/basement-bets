"""Board/ingestion health metrics.

Used by update_data_health.py and optionally by API endpoints.

Goals:
- Actionable per-league board coverage stats
- Low-cost queries (use latest_odds_snapshots view when available)

"""

from __future__ import annotations

import os
import json
from datetime import datetime, timedelta

from src.database import get_admin_db_connection, _exec


def compute_board_health(league: str, days: int = 3) -> dict:
    league = (league or '').upper().strip()
    days = max(1, min(int(days or 3), 14))

    with get_admin_db_connection() as conn:
        # Use ET day window to match /api/board logic.
        start_et = _exec(conn, "SELECT (NOW() AT TIME ZONE 'America/New_York')::date").fetchone()[0]
        end_et = _exec(conn, "SELECT ((NOW() AT TIME ZONE 'America/New_York')::date + (%s || ' days')::interval)::date", (days - 1,)).fetchone()[0]

        rows = _exec(
            conn,
            """
            WITH base_events AS (
              SELECT e.id, DATE(e.start_time AT TIME ZONE 'America/New_York') AS day_et
              FROM events e
              WHERE e.league = %s
                AND DATE(e.start_time AT TIME ZONE 'America/New_York') BETWEEN %s AND %s
            ),
            per_event AS (
              SELECT e.id AS event_id,
                e.day_et,
                MAX(CASE WHEN o.market_type='SPREAD' THEN 1 ELSE 0 END) AS has_spread,
                MAX(CASE WHEN o.market_type='TOTAL' THEN 1 ELSE 0 END) AS has_total,
                MAX(CASE WHEN o.market_type='MONEYLINE' THEN 1 ELSE 0 END) AS has_ml
              FROM base_events e
              LEFT JOIN (
                SELECT DISTINCT ON (event_id, market_type)
                  event_id, market_type
                FROM odds_snapshots
                WHERE captured_at >= NOW() - INTERVAL '7 days'
                ORDER BY event_id, market_type, captured_at DESC
              ) o ON o.event_id = e.id
              GROUP BY e.id, e.day_et
            )
            SELECT
              COUNT(*)::int AS events_total,
              SUM(has_spread)::int AS with_spread,
              SUM(has_total)::int AS with_total,
              SUM(has_ml)::int AS with_moneyline,
              SUM(CASE WHEN day_et = %s THEN 1 ELSE 0 END)::int AS today_events_total,
              SUM(CASE WHEN day_et = %s THEN has_spread ELSE 0 END)::int AS today_with_spread,
              SUM(CASE WHEN day_et = %s THEN has_total ELSE 0 END)::int AS today_with_total,
              SUM(CASE WHEN day_et = %s THEN has_ml ELSE 0 END)::int AS today_with_moneyline
            FROM per_event;
            """,
            (league, start_et, end_et, start_et, start_et, start_et, start_et),
        ).fetchone()

        # row access is handled by _get() below (works for tuple + DictRow)

        # Snapshot volume (recent)
        snap_rows = _exec(
            conn,
            """
            SELECT market_type, COUNT(*)::int AS n
            FROM odds_snapshots
            WHERE captured_at >= NOW() - INTERVAL '6 hours'
              AND event_id IN (
                SELECT id FROM events
                WHERE league=%s
                  AND start_time >= NOW() - INTERVAL '3 days'
                  AND start_time <= NOW() + INTERVAL '7 days'
              )
            GROUP BY market_type
            ORDER BY market_type;
            """,
            (league,),
        ).fetchall()

        # Normalize list rows as dicts when possible.
        try:
            snap_rows = [dict(r) if (r is not None and not isinstance(r, dict) and hasattr(r, 'keys')) else r for r in (snap_rows or [])]
        except Exception:
            pass

    def _get(row, key: str, idx: int, default=0):
        """Safely read from dict-like OR tuple-like cursor rows."""
        if row is None:
            return default

        # 1) dict
        if isinstance(row, dict):
            return row.get(key, default)

        # 2) try key access (DictRow supports this; tuples will throw TypeError)
        try:
            return row[key]
        except Exception:
            pass

        # 3) positional fallback
        try:
            return row[idx]
        except Exception:
            return default

    events_total = int(_get(rows, 'events_total', 0, 0) or 0)
    with_spread = int(_get(rows, 'with_spread', 1, 0) or 0)
    with_total = int(_get(rows, 'with_total', 2, 0) or 0)
    with_ml = int(_get(rows, 'with_moneyline', 3, 0) or 0)
    today_events_total = int(_get(rows, 'today_events_total', 4, 0) or 0)
    today_with_spread = int(_get(rows, 'today_with_spread', 5, 0) or 0)
    today_with_total = int(_get(rows, 'today_with_total', 6, 0) or 0)
    today_with_ml = int(_get(rows, 'today_with_moneyline', 7, 0) or 0)

    pct = lambda a, b: (float(a) / float(b)) if b else 0.0

    markets_6h = {}
    for r in (snap_rows or []):
        mt = _get(r, 'market_type', 0, None)
        n = _get(r, 'n', 1, 0)
        if mt is None:
            continue
        try:
            markets_6h[str(mt)] = int(n or 0)
        except Exception:
            markets_6h[str(mt)] = 0

    return {
        'league': league,
        'window_days': days,
        'events_total': events_total,
        'with_spread': with_spread,
        'with_total': with_total,
        'with_moneyline': with_ml,
        'pct_with_spread': round(pct(with_spread, events_total), 4),
        'pct_with_total': round(pct(with_total, events_total), 4),
        'pct_with_moneyline': round(pct(with_ml, events_total), 4),
        'missing_spread_pct': round(1.0 - pct(with_spread, events_total), 4) if events_total else 0.0,
        'missing_total_pct': round(1.0 - pct(with_total, events_total), 4) if events_total else 0.0,
        'missing_moneyline_pct': round(1.0 - pct(with_ml, events_total), 4) if events_total else 0.0,
        'today_events_total': today_events_total,
        'today_with_spread': today_with_spread,
        'today_with_total': today_with_total,
        'today_with_moneyline': today_with_ml,
        'today_pct_with_spread': round(pct(today_with_spread, today_events_total), 4),
        'today_pct_with_total': round(pct(today_with_total, today_events_total), 4),
        'today_missing_spread_pct': round(1.0 - pct(today_with_spread, today_events_total), 4) if today_events_total else 0.0,
        'today_missing_total_pct': round(1.0 - pct(today_with_total, today_events_total), 4) if today_events_total else 0.0,
        'snapshots_last_6h_by_market': markets_6h,
        'generated_at': datetime.utcnow().isoformat() + 'Z',
    }


def status_from_health(h: dict) -> str:
    # Alert if today's totals coverage (or window coverage if no today games) is too low.
    thresh = float(os.getenv('TOTALS_MISSING_ALERT_PCT', '0.40'))
    if not h or not h.get('events_total'):
        return 'stale'
    if (h.get('today_events_total') or 0) > 0:
        if float(h.get('today_missing_total_pct') or 0.0) > thresh:
            return 'alert'
        return 'ok'
    if float(h.get('missing_total_pct') or 0.0) > thresh:
        return 'alert'
    return 'ok'


def notes_from_health(h: dict) -> str:
    try:
        return json.dumps(h, sort_keys=True)
    except Exception:
        return str(h)
