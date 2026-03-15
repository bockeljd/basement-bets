#!/usr/bin/env python3
"""Print Top N NCAAM picks from cached daily_top_picks table.

Designed for cron: fast, no model compute.

Outputs a ready-to-send text block.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from typing import Optional

# Allow running from repo root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.database import get_db_connection, _exec, ensure_recommended_slates_tables


def _ev_from_rec(rec: dict) -> Optional[float]:
    # rec['edge'] is like "+12.3%" (string). Convert to 0.123.
    try:
        e = rec.get('edge')
        if e is None:
            return None
        if isinstance(e, (int, float)):
            return float(e)
        s = str(e).strip().replace('%', '')
        return float(s) / 100.0
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--date', default=None, help='ET date YYYY-MM-DD (default today ET)')
    ap.add_argument('--limit', type=int, default=100)
    args = ap.parse_args()

    with get_db_connection() as conn:
        date_et = args.date
        if not date_et:
            date_et = _exec(conn, "SELECT (NOW() AT TIME ZONE 'America/New_York')::date::text").fetchone()[0]

        rows = _exec(conn, """
          SELECT d.event_id, d.rec_json,
                 (e.start_time AT TIME ZONE 'America/New_York') as start_et,
                 e.away_team, e.home_team
          FROM daily_top_picks d
          JOIN events e ON e.id=d.event_id
          WHERE d.date_et=%s AND d.is_actionable=TRUE AND d.rec_json IS NOT NULL
          ORDER BY (regexp_replace(COALESCE(d.rec_json->>'edge','0'),'[^0-9\\.\\-]+','','g'))::float DESC
          LIMIT %s
        """, (date_et, int(args.limit))).fetchall()

    if not rows:
        # Add basic diagnostics so we know whether we evaluated the slate or skipped due to missing data.
        with get_db_connection() as conn:
            stats = _exec(conn, """
              SELECT
                COUNT(*) as total,
                SUM(CASE WHEN is_actionable THEN 1 ELSE 0 END) as actionable,
                -- NOTE: psycopg2 uses 'pyformat' paramstyle; literal % must be escaped as %%.
                SUM(CASE WHEN reason ILIKE '%%Market Data Waiting%%' OR reason ILIKE '%%No Line%%' THEN 1 ELSE 0 END) as no_line,
                SUM(CASE WHEN reason ILIKE '%%Torvik%%' AND (reason ILIKE '%%unavailable%%' OR reason ILIKE '%%no data%%') THEN 1 ELSE 0 END) as missing_torvik,
                SUM(CASE WHEN reason ILIKE '%%No bet%%' OR reason ILIKE '%%Pass%%' THEN 1 ELSE 0 END) as no_bet,
                SUM(CASE WHEN reason ILIKE '%%error%%' THEN 1 ELSE 0 END) as errors
              FROM daily_top_picks
              WHERE date_et=%s AND league='NCAAM'
            """, (date_et,)).fetchone()

        total = int(stats['total'] or 0) if stats else 0
        print(f"No bets for {date_et} (no edges passed gates)")
        if total:
            print("Diagnostics (daily_top_picks):")
            print(f"- total_events: {total}")
            print(f"- actionable: {int(stats['actionable'] or 0)}")
            print(f"- no_line: {int(stats['no_line'] or 0)}")
            print(f"- missing_torvik: {int(stats['missing_torvik'] or 0)}")
            print(f"- no_bet: {int(stats['no_bet'] or 0)}")
            print(f"- errors: {int(stats['errors'] or 0)}")
        else:
            print("Diagnostics: daily_top_picks table has 0 rows for this date (ingestion/build job may not have run).")
        return

    # Persist the exact slate we are about to send.
    slate_id = None
    try:
        ensure_recommended_slates_tables()
        import uuid
        slate_id = str(uuid.uuid4())
        with get_db_connection() as conn:
            _exec(conn, """
              INSERT INTO recommended_slates (id, league, date_et, source)
              VALUES (%s, %s, %s, %s)
            """, (slate_id, 'NCAAM', date_et, 'cached'))

            # Attempt to map each daily_top_picks row to a concrete model_predictions id.
            # Best-effort: match on event_id + (selection OR line/price) and take the latest.
            for i, r in enumerate(rows, start=1):
                rec = r['rec_json'] or {}
                sel = rec.get('selection')
                line = rec.get('market_line')
                price = rec.get('price')

                pid = None
                try:
                    q = """
                      SELECT id
                      FROM model_predictions
                      WHERE event_id=%s
                        AND (selection=%s OR (bet_line=%s AND bet_price=%s))
                      ORDER BY analyzed_at DESC
                      LIMIT 1
                    """
                    row = _exec(conn, q, (r['event_id'], sel, line, price)).fetchone()
                    if row:
                        pid = (row['id'] if isinstance(row, dict) else row[0])
                except Exception:
                    pid = None

                # Always write an item row. If we can't map to a persisted prediction id,
                # store a stable fallback key and rely on event_id/selection/price for later re-linking.
                item_pid = str(pid) if pid else f"unlinked:{r['event_id']}:{int(i)}"
                _exec(conn, """
                  INSERT INTO recommended_slate_items (
                    slate_id, prediction_id, rank,
                    event_id, selection, bet_price, bet_line, market_type
                  )
                  VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                  ON CONFLICT (slate_id, prediction_id) DO NOTHING
                """, (
                    slate_id,
                    item_pid,
                    int(i),
                    str(r['event_id']) if r.get('event_id') is not None else None,
                    str(sel) if sel is not None else None,
                    int(price) if price is not None else None,
                    float(line) if line is not None else None,
                    str(rec.get('market_type') or r.get('market_type') or '') or None,
                ))
            conn.commit()
    except Exception:
        slate_id = None

    print(f"Actionable Plays for {date_et} • Sorted by EV%")
    if slate_id:
        print(f"[recommended_slate] id={slate_id} items={min(len(rows), int(args.limit))}")

    for i, r in enumerate(rows, start=1):
        rec = r['rec_json'] or {}
        start_et = r.get('start_et')
        t = start_et.strftime('%-I:%M %p ET') if hasattr(start_et, 'strftime') else ''
        matchup = f"{r.get('away_team')} @ {r.get('home_team')}"
        sel = rec.get('selection')
        odds = rec.get('price')
        ev_pct = rec.get('edge')
        conf = rec.get('confidence')
        # Normalize odds
        odds_s = f"{odds:+d}" if isinstance(odds, int) else (str(odds) if odds is not None else 'odds n/a')
        print(f"{i}) {t} • {matchup} • {sel} • {odds_s} • EV {ev_pct} • {conf}")


if __name__ == '__main__':
    main()
