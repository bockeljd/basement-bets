"""Freeze the daily pregame NCAAM recommendations in one transaction."""
from src.database import _exec, get_db_connection, ensure_recommended_slates_tables
from src.utils.model_performance import rank_top6_items
from psycopg2.extras import Json


def _slate_items(conn, slate_id):
    rows = _exec(conn, """
        SELECT i.rank,i.selection,i.bet_price,i.bet_line,i.market_type,
               e.home_team,e.away_team,e.start_time,i.snapshot->>'book' AS book,
               i.snapshot->>'edge' AS edge,i.snapshot->>'confidence' AS confidence
        FROM recommended_slate_items i LEFT JOIN events e ON e.id=i.event_id
        WHERE i.slate_id=%s AND i.rank BETWEEN 1 AND 6 ORDER BY i.rank
    """, (slate_id,)).fetchall()
    return [dict(row) for row in rows]


def publish_slate(date_et=None):
    ensure_recommended_slates_tables()
    with get_db_connection() as conn:
        _exec(conn, "SET LOCAL TIME ZONE 'UTC'")
        today = _exec(conn, "SELECT (NOW() AT TIME ZONE 'America/New_York')::date::text").fetchone()[0]
        day = str(date_et or today)
        slate_id = f"NCAAM:{day}:cached"
        _exec(conn, "SELECT pg_advisory_xact_lock(hashtext(%s))", (slate_id,))
        existing = _exec(conn, """
            SELECT id FROM recommended_slates WHERE league='NCAAM' AND date_et=%s
            AND source='cached' ORDER BY created_at,id LIMIT 1
        """, (day,)).fetchone()
        if existing:
            items = _slate_items(conn, existing[0])
            conn.commit()
            return {"status": "already_locked", "slate_id": existing[0], "items": items}
        if day != today:
            raise ValueError("Only today's pregame slate can be published")
        rows = _exec(conn, """
            SELECT d.event_id,d.is_actionable,d.rec_json,d.computed_at,d.model_version,
                   e.start_time,p.id,p.market_type,p.selection,p.bet_line,p.bet_price,p.book,
                   quote.captured_at,quote.price AS current_price,quote.line_value AS current_line,
                   opposite.price AS opposite_price,opposite.line_value AS opposite_line,
                   opposite.captured_at AS opposite_at
            FROM daily_top_picks d JOIN events e ON e.id=d.event_id
            LEFT JOIN model_predictions p ON p.id=d.rec_json->>'prediction_id'
                AND p.event_id=d.event_id AND p.model_version=d.model_version
                AND p.analyzed_at <= NOW() AND p.analyzed_at < e.start_time
            LEFT JOIN LATERAL (
                SELECT o.captured_at,o.price,o.line_value FROM odds_snapshots o
                WHERE o.event_id=p.event_id AND o.book=p.book AND o.market_type=p.market_type
                    AND o.side=upper(d.rec_json->>'side')
                    AND o.captured_at BETWEEN NOW()-interval '90 minutes' AND NOW()
                ORDER BY o.captured_at DESC,o.id DESC LIMIT 1
            ) quote ON TRUE
            LEFT JOIN LATERAL (
                SELECT o.price,o.line_value,o.captured_at FROM odds_snapshots o
                WHERE o.event_id=p.event_id AND o.book=p.book AND o.market_type=p.market_type
                    AND o.side=CASE upper(d.rec_json->>'side') WHEN 'HOME' THEN 'AWAY'
                        WHEN 'AWAY' THEN 'HOME' WHEN 'OVER' THEN 'UNDER' WHEN 'UNDER' THEN 'OVER' END
                    AND o.captured_at BETWEEN NOW()-interval '90 minutes' AND NOW()
                ORDER BY o.captured_at DESC,o.id DESC LIMIT 1
            ) opposite ON TRUE
            WHERE d.date_et=%s AND d.league='NCAAM' AND e.league='NCAAM'
                AND (e.start_time AT TIME ZONE 'America/New_York')::date=%s::date
            ORDER BY d.event_id
        """, (day, day)).fetchall()
        if not rows:
            raise RuntimeError("NCAAM daily cache unavailable")
        now = _exec(conn, "SELECT clock_timestamp()").fetchone()[0]
        candidates = []
        for row in rows:
            rec = row['rec_json'] or {}
            if row['start_time'] <= now or not row['is_actionable'] or rec.get('top6_eligible') is False:
                continue
            if not row['id']:
                raise RuntimeError(f"Missing persisted prediction for {row['event_id']}")
            if (not row['captured_at'] or row['current_price'] != row['bet_price']
                    or row['current_line'] != row['bet_line']):
                continue
            candidates.append({**rec, **dict(row)})
        items = rank_top6_items(candidates, limit=6)
        _exec(conn, """INSERT INTO recommended_slates(id,league,date_et,source)
            VALUES (%s,'NCAAM',%s,'cached')""", (slate_id, day))
        for item in items:
            snapshot = {**item['rec_json'], 'model_version': item['model_version'],
                        'book': item['book'], 'computed_at': item['computed_at'].isoformat()}
            snapshot['quote_captured_at'] = item['captured_at'].isoformat()
            opposite_line = item['bet_line']
            if item['market_type'].startswith('SPREAD') and opposite_line is not None:
                opposite_line = -opposite_line
            if item['opposite_price'] and item['opposite_line'] == opposite_line:
                snapshot['opposite_price'] = item['opposite_price']
                snapshot['opposite_captured_at'] = item['opposite_at'].isoformat()
            _exec(conn, """INSERT INTO recommended_slate_items
                (slate_id,prediction_id,rank,event_id,selection,bet_price,bet_line,market_type,snapshot)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (slate_id,item['id'],item['rank'],item['event_id'],item['selection'],
                 item['bet_price'],item['bet_line'],item['market_type'],Json(snapshot)))
        published = _slate_items(conn, slate_id)
        conn.commit()
        return {"status": "published" if published else "no_eligible_picks",
                "slate_id": slate_id, "items": published}
