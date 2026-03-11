import sys
import os
import json
import datetime
from datetime import datetime as dt, timedelta, timezone

# Allow running from repo root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from src.database import get_admin_db_connection, get_db_connection, _exec
from src.models.ncaam_market_first_model_v2 import NCAAMMarketFirstModelV2
from src.agents.data_quality_agent import DataQualityAgent


def ensure_table():
    sql = """
    CREATE TABLE IF NOT EXISTS daily_top_picks (
      date_et DATE NOT NULL,
      event_id TEXT NOT NULL,
      league TEXT NOT NULL DEFAULT 'NCAAM',
      computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      model_version TEXT,

      is_actionable BOOLEAN NOT NULL DEFAULT FALSE,
      reason TEXT,

      rec_json JSONB,
      context_json JSONB,

      PRIMARY KEY(date_et, event_id)
    );

    CREATE INDEX IF NOT EXISTS ix_daily_top_picks_date_league ON daily_top_picks(date_et, league);
    """
    with get_admin_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()


def fetch_event_ids_for_date(date_et: str, limit_games: int = 250):
    # Use same dedupe logic as /api/board.
    q = """
    WITH base_events AS (
      SELECT e.*,
        DATE(e.start_time AT TIME ZONE 'America/New_York') AS day_et,
        LOWER(regexp_replace(
          replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(COALESCE(e.home_team,''),
            'North Carolina State', 'NC State'), 'N.C. State', 'NC State'), 'N.C. St.', 'NC State'), 'NC St.', 'NC State'),
            'App State', 'Appalachian State'), 'Appalachian St.', 'Appalachian State'), 'Appalachian St', 'Appalachian State'),
            'South Carolina Upstate', 'USC Upstate'), 'U.S.C. Upstate', 'USC Upstate'),
            'Long Island University', 'LIU'), 'L.I.U.', 'LIU'),
            'St. Francis', 'Saint Francis'),
          '[^a-z0-9]+', '', 'g'
        )) AS home_key,
        LOWER(regexp_replace(
          replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(COALESCE(e.away_team,''),
            'North Carolina State', 'NC State'), 'N.C. State', 'NC State'), 'N.C. St.', 'NC State'), 'NC St.', 'NC State'),
            'App State', 'Appalachian State'), 'Appalachian St.', 'Appalachian State'), 'Appalachian St', 'Appalachian State'),
            'South Carolina Upstate', 'USC Upstate'), 'U.S.C. Upstate', 'USC Upstate'),
            'Long Island University', 'LIU'), 'L.I.U.', 'LIU'),
            'St. Francis', 'Saint Francis'),
          '[^a-z0-9]+', '', 'g'
        )) AS away_key,
        CASE
          WHEN e.id LIKE 'action:ncaam:%%' THEN 0
          WHEN e.id LIKE 'espn:ncaam:%%' THEN 1
          ELSE 2
        END AS src_rank
      FROM events e
      WHERE e.league='NCAAM'
        AND DATE(e.start_time AT TIME ZONE 'America/New_York') = %(d)s
    ),
    dedup_events AS (
      SELECT *
      FROM (
        SELECT *,
          ROW_NUMBER() OVER (PARTITION BY league, day_et, home_key, away_key ORDER BY src_rank ASC, start_time ASC) AS rn
        FROM base_events
      ) t
      WHERE rn = 1
    )
    SELECT id
    FROM dedup_events
    ORDER BY start_time ASC
    LIMIT %(lim)s
    """
    with get_db_connection() as conn:
        rows = _exec(conn, q, {"d": date_et, "lim": int(limit_games)}).fetchall()
        return [r['id'] if isinstance(r, dict) else r[0] for r in rows]


def upsert_pick(date_et: str, event_id: str, res: dict, conn=None):
    rec = None
    try:
        rec = (res.get('recommendations') or [None])[0]
    except Exception:
        rec = None

    is_actionable = bool(rec)
    reason = None
    if not is_actionable:
        reason = (res.get('block_reason') or res.get('headline') or res.get('recommendation') or res.get('error') or 'No bet') if isinstance(res, dict) else 'No bet'

    # context_json is a JSON string currently in the model; store as JSONB if possible
    ctx = None
    try:
        cj = res.get('context_json')
        if cj:
            ctx = json.loads(cj) if isinstance(cj, str) else cj
    except Exception:
        ctx = None

    sql = """
    INSERT INTO daily_top_picks(date_et, event_id, league, computed_at, model_version, is_actionable, reason, rec_json, context_json)
    VALUES (%(d)s, %(eid)s, 'NCAAM', NOW(), %(mv)s, %(act)s, %(reason)s, %(rec)s::jsonb, %(ctx)s::jsonb)
    ON CONFLICT (date_et, event_id) DO UPDATE SET
      computed_at = EXCLUDED.computed_at,
      model_version = EXCLUDED.model_version,
      is_actionable = EXCLUDED.is_actionable,
      reason = EXCLUDED.reason,
      rec_json = EXCLUDED.rec_json,
      context_json = EXCLUDED.context_json
    """
    payload = {
        "d": date_et,
        "eid": event_id,
        "mv": res.get('model_version') if isinstance(res, dict) else None,
        "act": bool(is_actionable),
        "reason": reason,
        "rec": json.dumps(rec) if rec is not None else None,
        "ctx": json.dumps(ctx) if ctx is not None else None,
    }

    if conn is None:
        with get_db_connection() as conn2:
            _exec(conn2, sql, payload)
            conn2.commit()
    else:
        _exec(conn, sql, payload)


def main():
    # date comes from env or argv
    date_et = None
    if len(sys.argv) > 1:
        date_et = sys.argv[1]
    if not date_et:
        date_et = dt.now(timezone.utc).astimezone(datetime.timezone(datetime.timedelta(hours=-5))).strftime('%Y-%m-%d')
        # better: ask DB for ET date
        try:
            with get_db_connection() as conn:
                date_et = _exec(conn, "SELECT (NOW() AT TIME ZONE 'America/New_York')::date::text").fetchone()[0]
        except Exception:
            pass

    limit_games = int(os.getenv('TOP_PICKS_LIMIT_GAMES', '250'))

    print(f"[{dt.now().isoformat()}] build_daily_top_picks date_et={date_et} limit_games={limit_games}")
    ensure_table()

    # Pre-flight data quality checks (and optional ingestion) so we don't skip games due to missing data.
    try:
        dq = DataQualityAgent()
        dq_out, _ = dq.run({
            'league': 'NCAAM',
            'date_et': date_et,
            # Keep default thresholds; can be overridden via env by passing values here later.
            'trigger_ingestion': str(os.getenv('DQ_TRIGGER_INGESTION', '0')).lower() in ('1', 'true', 'yes'),
        })
        print(f"data_quality: {json.dumps(dq_out or {}, default=str)}")
    except Exception as e:
        print(f"[data_quality] check failed (continuing): {e}")

    event_ids = fetch_event_ids_for_date(date_et, limit_games=limit_games)
    print(f"events: {len(event_ids)}")

    model = NCAAMMarketFirstModelV2()

    ok = 0
    err = 0

    # Diagnostics: track why games are producing no picks (data vs gates).
    diag = {
        'total_events': 0,
        'actionable': 0,
        'no_line': 0,
        'missing_torvik': 0,
        'no_bet': 0,
        'errors': 0,
        'other_reasons': {},
    }

    # Batch DB writes to reduce Neon egress: single connection + single commit.
    with get_db_connection() as conn:
        for eid in event_ids:
            diag['total_events'] += 1
            try:
                # Use strict gates for cached picks so we don't surface negative/no-edge plays.
                res = model.analyze(eid, relax_gates=False, persist=True)

                # Diagnose outcome
                try:
                    rec0 = (res.get('recommendations') or [None])[0] if isinstance(res, dict) else None
                    if rec0:
                        diag['actionable'] += 1
                    else:
                        reason = (res.get('block_reason') or res.get('headline') or res.get('recommendation') or res.get('error') or 'No bet') if isinstance(res, dict) else 'No bet'
                        rlow = str(reason).lower()
                        if 'market data waiting' in rlow or 'no line' in rlow:
                            diag['no_line'] += 1
                        elif 'torvik' in rlow and ('unavailable' in rlow or 'no data' in rlow):
                            diag['missing_torvik'] += 1
                        elif 'no bet' in rlow or 'pass' in rlow:
                            diag['no_bet'] += 1
                        else:
                            diag['other_reasons'][str(reason)] = int(diag['other_reasons'].get(str(reason), 0)) + 1
                except Exception:
                    pass

                upsert_pick(date_et, eid, res if isinstance(res, dict) else {}, conn=conn)
                ok += 1
            except Exception as e:
                err += 1
                diag['errors'] += 1
                # still upsert a no-bet row with error reason
                try:
                    upsert_pick(date_et, eid, {"recommendations": [], "error": str(e), "model_version": getattr(model, 'VERSION', None), "block_reason": str(e)}, conn=conn)
                except Exception:
                    pass

        conn.commit()

    print(f"done ok={ok} err={err}")

    # Print a compact diagnostic summary (helps distinguish 'market efficient' vs 'data missing').
    try:
        print("diagnostics:")
        print(f"- total_events: {diag['total_events']}")
        print(f"- actionable: {diag['actionable']}")
        print(f"- no_line: {diag['no_line']}")
        print(f"- missing_torvik: {diag['missing_torvik']}")
        print(f"- no_bet: {diag['no_bet']}")
        print(f"- errors: {diag['errors']}")
        if diag.get('other_reasons'):
            # show top 5 other reasons
            items = sorted(diag['other_reasons'].items(), key=lambda kv: kv[1], reverse=True)[:5]
            for k, v in items:
                print(f"- other: {v} × {k}")
    except Exception:
        pass


if __name__ == '__main__':
    main()
