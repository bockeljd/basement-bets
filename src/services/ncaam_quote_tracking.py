"""Capture same-book decision and closing quotes for archived NCAAM forecasts."""
from src.database import _exec


def _pair_query(comparison):
    return f"""
                SELECT d.*, jsonb_build_object('as_of',d.as_of,'book',d.book,
                       'saved_at',clock_timestamp(),'sides',quotes.sides) AS snapshot
                FROM due d CROSS JOIN LATERAL (
                    SELECT jsonb_object_agg(w.side, CASE WHEN o.captured_at IS NOT NULL THEN
                        jsonb_build_object('line',o.line_value,'price',o.price,'quote_at',o.captured_at,
                            'fresh',o.captured_at >= d.as_of-interval '90 minutes') END) AS sides
                    FROM unnest(CASE WHEN d.market LIKE 'TOTAL%%' THEN ARRAY['OVER','UNDER']
                                ELSE ARRAY['HOME','AWAY'] END) w(side)
                    LEFT JOIN LATERAL (
                        SELECT price,line_value,captured_at FROM odds_snapshots
                        WHERE event_id=d.event_id AND market_type=d.market AND side=w.side
                          AND lower(book)=lower(d.book) AND abs(price)>=100 AND captured_at {comparison} d.as_of
                        ORDER BY captured_at DESC,id DESC LIMIT 1
                    ) o ON true
                ) quotes
    """


def capture_due_quotes(conn):
    """Resolve due checkpoints from archived quotes, including after worker downtime."""
    for stage in ("lock", "close"):
        column = stage + "_quotes"
        boundary = "e.start_time - interval '30 minutes'" if stage == "lock" else "e.start_time"
        comparison = "<=" if stage == "lock" else "<"
        # Include all three full-game markets, even when the model passes the game.
        # Keep the original schedule boundary when a tip is later rescheduled.
        _exec(conn, f"""
            WITH due AS (
                SELECT DISTINCT e.id AS event_id,{boundary} AS as_of
                FROM daily_top_picks d JOIN events e ON e.id=d.event_id
                WHERE d.league='NCAAM' AND {boundary} <= now()
                  AND NOT EXISTS (SELECT 1 FROM ncaam_market_checkpoints c WHERE
                      c.event_id=e.id AND c.stage=%s AND c.as_of={boundary})
            )
            INSERT INTO ncaam_market_checkpoints(event_id,stage,as_of,quotes)
            SELECT d.event_id,%s,d.as_of,COALESCE(b.books,'{{}}'::jsonb)
            FROM due d CROSS JOIN LATERAL (
                SELECT jsonb_object_agg(book, markets) AS books FROM (
                    SELECT book,jsonb_object_agg(market_type,sides) AS markets FROM (
                        SELECT book,market_type,jsonb_object_agg(side,jsonb_build_object(
                            'price',price,'line',line_value,'quote_at',captured_at,
                            'fresh',captured_at>=d.as_of-interval '90 minutes')) AS sides
                        FROM (
                            SELECT DISTINCT ON (lower(book),market_type,side)
                                lower(book) AS book,market_type,side,price,line_value,captured_at
                            FROM odds_snapshots
                            WHERE event_id=d.event_id AND captured_at {comparison} d.as_of
                              AND market_type IN ('SPREAD','TOTAL','MONEYLINE') AND abs(price)>=100
                              AND lower(book) NOT IN ('','consensus','unknown','action_open','open')
                              AND lower(book) NOT LIKE 'action\\_book\\_%%'
                            ORDER BY lower(book),market_type,side,captured_at DESC,id DESC
                        ) latest GROUP BY book,market_type
                    ) by_market GROUP BY book
                ) by_book
            ) b ON CONFLICT DO NOTHING
        """, (stage,stage))
        _exec(conn, f"""
            WITH due AS (
                SELECT a.event_id,a.model_version,a.market,a.side,a.cohort,a.book,
                       {boundary} AS as_of
                FROM ncaam_ev_observations a JOIN events e ON e.id=a.event_id
                WHERE {boundary} <= clock_timestamp()
                  AND (a.{column} IS NULL OR (a.{column}->>'as_of')::timestamptz <> {boundary})
            ), captured AS (
                {_pair_query(comparison)}
            )
            UPDATE ncaam_ev_observations a SET {column}=c.snapshot
            FROM captured c WHERE (a.event_id,a.model_version,a.market,a.side,a.cohort)
                              =(c.event_id,c.model_version,c.market,c.side,c.cohort)
        """)

    # A published pick can use a different book from the first qualifying observation.
    _exec(conn, f"""
        WITH due AS (
            SELECT i.slate_id,i.prediction_id,i.event_id,i.market_type AS market,
                   i.snapshot->>'book' AS book,e.start_time AS as_of
            FROM recommended_slate_items i JOIN events e ON e.id=i.event_id
            WHERE e.league='NCAAM' AND i.snapshot->'lock_quotes' IS NOT NULL
              AND i.snapshot->'close_quotes' IS NULL AND e.start_time <= clock_timestamp()
        ), captured AS ({_pair_query("<")})
        UPDATE recommended_slate_items i
        SET snapshot=jsonb_set(i.snapshot,'{{close_quotes}}',c.snapshot)
        FROM captured c WHERE i.slate_id=c.slate_id AND i.prediction_id=c.prediction_id
    """)
