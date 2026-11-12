import sys
import os
import datetime

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from src.database import get_admin_db_connection


def ensure_table():
    sql = """
    CREATE TABLE IF NOT EXISTS data_health (
      source TEXT PRIMARY KEY,
      last_success_at TIMESTAMPTZ,
      last_row_count BIGINT,
      status TEXT NOT NULL DEFAULT 'unknown',
      notes TEXT,
      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """
    with get_admin_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()


def upsert(source: str, status: str, row_count: int | None = None, notes: str | None = None):
    sql = """
    INSERT INTO data_health(source, last_success_at, last_row_count, status, notes, updated_at)
    VALUES (%s, NOW(), %s, %s, %s, NOW())
    ON CONFLICT (source) DO UPDATE SET
      last_success_at=EXCLUDED.last_success_at,
      last_row_count=COALESCE(EXCLUDED.last_row_count, data_health.last_row_count),
      status=EXCLUDED.status,
      notes=EXCLUDED.notes,
      updated_at=NOW();
    """
    with get_admin_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (source, row_count, status, notes))
        conn.commit()


def main():
    print(f"[{datetime.datetime.now()}] update_data_health")
    ensure_table()

    # Odds health
    with get_admin_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM odds_snapshots WHERE captured_at >= NOW() - INTERVAL '6 hours'")
            n = cur.fetchone()[0]
    status = 'ok' if n and n > 0 else 'stale'
    upsert('odds', status=status, row_count=n, notes='rows in last 6h')

    # Board coverage health (actionable, per league)
    try:
        from src.scripts.board_health import compute_board_health, status_from_health, notes_from_health
        for lg in ['NCAAM']:
            h = compute_board_health(lg, days=3)
            st = status_from_health(h)
            upsert(f'board:{lg}', status=st, row_count=h.get('events_total'), notes=notes_from_health(h))

        # If board health succeeded, clear any prior error sentinel row.
        try:
            with get_admin_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM data_health WHERE source='board:ERROR'")
                conn.commit()
        except Exception:
            pass

    except Exception as e:
        import traceback
        upsert('board:ERROR', status='error', row_count=None, notes=traceback.format_exc())

    # (Seasonal) Remove irrelevant board rows (NFL season over; EPL not modeled currently)
    try:
        with get_admin_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM data_health WHERE source IN ('board:NFL','board:EPL')")
            conn.commit()
    except Exception:
        pass

    # KenPom health (daily snapshots)
    with get_admin_db_connection() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute("SELECT MAX(asof_date)::date FROM kenpom_team_ratings_daily")
                max_dt = cur.fetchone()[0]
                cur.execute("SELECT (NOW() AT TIME ZONE 'America/New_York')::date")
                today = cur.fetchone()[0]

                if max_dt is None:
                    status = 'stale'
                    notes = '{"reason":"no rows"}'
                    n = 0
                else:
                    # Count per-table for the latest asof_date
                    cur.execute("SELECT COUNT(*) FROM kenpom_team_ratings_daily WHERE asof_date=%s", (max_dt,))
                    n_team = cur.fetchone()[0]
                    cur.execute("SELECT COUNT(*) FROM kenpom_home_court_daily WHERE asof_date=%s", (max_dt,))
                    n_hca = cur.fetchone()[0]
                    cur.execute("SELECT COUNT(*) FROM kenpom_ref_ratings_daily WHERE asof_date=%s", (max_dt,))
                    n_ref = cur.fetchone()[0]
                    cur.execute("SELECT COUNT(*) FROM kenpom_player_stats_daily WHERE asof_date=%s", (max_dt,))
                    n_player = cur.fetchone()[0]

                    n = int(n_team or 0) + int(n_hca or 0) + int(n_ref or 0) + int(n_player or 0)
                    # OK if data is from today ET or yesterday ET (since this runs daily).
                    status = 'ok' if (max_dt >= (today - datetime.timedelta(days=1)) and n_team and n_team > 0) else 'stale'
                    notes = (
                        '{'
                        f'"asof_date":"{max_dt}",'
                        f'"team":{int(n_team or 0)},'
                        f'"home_court":{int(n_hca or 0)},'
                        f'"refs":{int(n_ref or 0)},'
                        f'"players":{int(n_player or 0)}'
                        '}'
                    )
            except Exception as e:
                n = None
                status = 'error'
                notes = str(e)
    upsert('kenpom', status=status, row_count=n, notes=notes)

    # Torvik health
    with get_admin_db_connection() as conn:
        with conn.cursor() as cur:
            try:
                # bt_team_metrics_daily.date can be TEXT in some deployments; cast to date for comparison.
                cur.execute("SELECT COUNT(*) FROM bt_team_metrics_daily WHERE (date::date) >= ((NOW() AT TIME ZONE 'America/New_York')::date - INTERVAL '2 days')")
                n = cur.fetchone()[0]
                status = 'ok' if n and n > 0 else 'stale'
            except Exception as e:
                n = None
                status = 'error'
                notes = str(e)
            else:
                notes = 'rows in last 2 days'
    upsert('torvik', status=status, row_count=n, notes=notes)

    # Results health
    with get_admin_db_connection() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute("SELECT COUNT(*) FROM game_results WHERE updated_at >= NOW() - INTERVAL '2 days'")
                n = cur.fetchone()[0]
                status = 'ok' if n and n > 0 else 'stale'
                notes = 'rows updated in last 2 days'
            except Exception as e:
                n = None
                status = 'error'
                notes = str(e)
    upsert('results', status=status, row_count=n, notes=notes)

    # Haslametrics health
    hasla_status = 'stale'
    hasla_n = 0
    hasla_notes = 'no rows in last 2 days'
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM haslametrics_ratings_daily WHERE updated_at > NOW() - INTERVAL '48 hours'"
                )
                hasla_n = cur.fetchone()[0]
                if hasla_n and hasla_n > 0:
                    hasla_status = 'ok'
                    hasla_notes = 'rows in last 48h'
    except Exception as e:
        hasla_status = 'error'
        hasla_notes = str(e)[:180]
    upsert('haslametrics', status=hasla_status, row_count=hasla_n, notes=hasla_notes)

    # Action Network public splits health
    splits_status = 'stale'
    splits_n = 0
    splits_notes = 'no splits in last 24h'
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM action_splits WHERE as_of_ts > NOW() - INTERVAL '24 hours'")
                splits_n = cur.fetchone()[0]
                if splits_n and splits_n > 0:
                    splits_status = 'ok'
                    splits_notes = 'splits in last 24h'
    except Exception as e:
        splits_status = 'error'
        splits_notes = str(e)[:180]
    upsert('action_splits', status=splits_status, row_count=splits_n, notes=splits_notes)

    print('[update_data_health] done')


if __name__ == '__main__':
    main()
