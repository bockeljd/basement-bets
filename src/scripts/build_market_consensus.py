import sys
import os
import datetime

# Allow running from repo root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from src.database import get_admin_db_connection


def ensure_objects():
    """Create/refresh the market_consensus materialized view."""

    mv_sql = """
    CREATE MATERIALIZED VIEW IF NOT EXISTS market_consensus AS
    WITH latest AS (
      SELECT DISTINCT ON (event_id, book, market_type, side)
        event_id, book, market_type, side, line_value, price, captured_at
      FROM odds_snapshots
      ORDER BY event_id, book, market_type, side, captured_at DESC
    ),
    open AS (
      SELECT DISTINCT ON (event_id, book, market_type, side)
        event_id, book, market_type, side, line_value, price, captured_at
      FROM odds_snapshots
      ORDER BY event_id, book, market_type, side, captured_at ASC
    ),
    spread_latest AS (
      SELECT event_id,
             COUNT(DISTINCT book) AS books_count,
             MAX(captured_at) AS as_of,
             MAX(line_value) FILTER (WHERE market_type='SPREAD' AND side='HOME' AND book='consensus') AS current_spread_home,
             MAX(price) FILTER (WHERE market_type='SPREAD' AND side='HOME' AND book='consensus') AS current_spread_price_home,
             (MAX(line_value) FILTER (WHERE market_type='SPREAD' AND side='HOME') - MIN(line_value) FILTER (WHERE market_type='SPREAD' AND side='HOME')) AS spread_disagreement
      FROM latest
      WHERE market_type='SPREAD' AND book <> 'action_open'
      GROUP BY event_id
    ),
    spread_open AS (
      SELECT event_id,
             MIN(captured_at) AS open_as_of,
             COALESCE(
               MAX(line_value) FILTER (WHERE market_type='SPREAD' AND side='HOME' AND book='action_open'),
               MAX(line_value) FILTER (WHERE market_type='SPREAD' AND side='HOME' AND book='consensus')
             ) AS open_spread_home,
             COALESCE(
               MAX(price) FILTER (WHERE market_type='SPREAD' AND side='HOME' AND book='action_open'),
               MAX(price) FILTER (WHERE market_type='SPREAD' AND side='HOME' AND book='consensus')
             ) AS open_spread_price_home
      FROM open
      WHERE market_type='SPREAD'
      GROUP BY event_id
    ),
    total_latest AS (
      SELECT event_id,
             MAX(captured_at) AS as_of,
             MAX(line_value) FILTER (WHERE market_type='TOTAL' AND side='OVER' AND book='consensus') AS current_total,
             MAX(price) FILTER (WHERE market_type='TOTAL' AND side='OVER' AND book='consensus') AS current_total_over_price,
             MAX(price) FILTER (WHERE market_type='TOTAL' AND side='UNDER' AND book='consensus') AS current_total_under_price,
             (MAX(line_value) FILTER (WHERE market_type='TOTAL' AND side='OVER') - MIN(line_value) FILTER (WHERE market_type='TOTAL' AND side='OVER')) AS total_disagreement
      FROM latest
      WHERE market_type='TOTAL' AND book <> 'action_open'
      GROUP BY event_id
    ),
    total_open AS (
      SELECT event_id,
             COALESCE(
               MAX(line_value) FILTER (WHERE market_type='TOTAL' AND side='OVER' AND book='action_open'),
               MAX(line_value) FILTER (WHERE market_type='TOTAL' AND side='OVER' AND book='consensus')
             ) AS open_total,
             COALESCE(
               MAX(price) FILTER (WHERE market_type='TOTAL' AND side='OVER' AND book='action_open'),
               MAX(price) FILTER (WHERE market_type='TOTAL' AND side='OVER' AND book='consensus')
             ) AS open_total_over_price,
             COALESCE(
               MAX(price) FILTER (WHERE market_type='TOTAL' AND side='UNDER' AND book='action_open'),
               MAX(price) FILTER (WHERE market_type='TOTAL' AND side='UNDER' AND book='consensus')
             ) AS open_total_under_price
      FROM open
      WHERE market_type='TOTAL'
      GROUP BY event_id
    )
    SELECT
      e.id AS event_id,
      COALESCE(sl.as_of, tl.as_of) AS as_of,

      so.open_spread_home,
      sl.current_spread_home,
      (sl.current_spread_home - so.open_spread_home) AS spread_move_home,

      to2.open_total,
      tl.current_total,
      (tl.current_total - to2.open_total) AS total_move,

      sl.spread_disagreement,
      tl.total_disagreement,

      COALESCE(sl.books_count, 0) AS books_count,
      'action_network'::text AS provider_used
    FROM events e
    LEFT JOIN spread_latest sl ON e.id = sl.event_id
    LEFT JOIN spread_open so ON e.id = so.event_id
    LEFT JOIN total_latest tl ON e.id = tl.event_id
    LEFT JOIN total_open to2 ON e.id = to2.event_id
    WHERE e.league = 'NCAAM';
    """

    # For concurrent refresh we need a unique index.
    ux_sql = "CREATE UNIQUE INDEX IF NOT EXISTS ux_market_consensus_event_id ON market_consensus(event_id);"

    with get_admin_db_connection() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute("SELECT pg_get_viewdef('market_consensus'::regclass, true);")
                vrow = cur.fetchone()
                vdef = (vrow[0] if vrow else '') or ''
                if vdef and 'action_open' not in vdef:
                    cur.execute("DROP MATERIALIZED VIEW IF EXISTS market_consensus;")
            except Exception:
                conn.rollback()
            cur.execute(mv_sql)
            cur.execute(ux_sql)
        conn.commit()


def refresh(concurrently: bool = True):
    with get_admin_db_connection() as conn:
        with conn.cursor() as cur:
            if concurrently:
                cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY market_consensus;")
            else:
                cur.execute("REFRESH MATERIALIZED VIEW market_consensus;")
        conn.commit()


def main():
    print(f"[{datetime.datetime.now()}] build_market_consensus: ensure + refresh")
    ensure_objects()
    try:
        refresh(concurrently=True)
    except Exception as e:
        # Concurrent refresh can fail if first time or if running inside a transaction.
        print(f"[build_market_consensus] concurrent refresh failed: {e}. Falling back to non-concurrent")
        refresh(concurrently=False)
    print("[build_market_consensus] done")


if __name__ == '__main__':
    main()
