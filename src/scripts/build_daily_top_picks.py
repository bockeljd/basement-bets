import sys
import os
import json
import datetime
from datetime import datetime as dt, timedelta, timezone

# Allow running from repo root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from src.utils.ncaam_slate import SLATE_CTE
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

    CREATE TABLE IF NOT EXISTS ncaam_ev_observations (
        event_id text NOT NULL, model_version text NOT NULL, market text NOT NULL,
        side text NOT NULL, cohort text NOT NULL, observed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        tip_at timestamptz NOT NULL, quote_at timestamptz NOT NULL, book text NOT NULL,
        line double precision NOT NULL, price integer NOT NULL, ev double precision NOT NULL,
        ev_cutoff double precision NOT NULL, win_prob double precision,
        PRIMARY KEY (event_id, model_version, market, side, cohort)
    );
    CREATE INDEX IF NOT EXISTS ix_daily_top_picks_date_league ON daily_top_picks(date_et, league);
    """
    with get_admin_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()


def fetch_event_ids_for_date(date_et: str, limit_games: int = 250, days: int = 3):
    # Use same dedupe logic and 3-day window as /api/board so UI multi-day slate is precomputed.
    start_d = dt.strptime(date_et, "%Y-%m-%d").date()
    end_d = start_d + timedelta(days=max(1, int(days)) - 1)
    q = SLATE_CTE + """
    SELECT id, day_et::text AS day_et
    FROM dedup_events
    ORDER BY start_time ASC
    LIMIT %s
    """
    with get_db_connection() as conn:
        rows = _exec(conn, q, (str(start_d), str(end_d), int(limit_games))).fetchall()
        out = []
        for r in rows:
            if isinstance(r, dict):
                out.append((r['id'], str(r.get('day_et') or date_et)))
            else:
                out.append((r[0], str(r[1] if len(r) > 1 and r[1] else date_et)))
        return out


def _normalize_rec_for_storage(
    rec: dict | None,
    *,
    start_time=None,
    home_team: str | None = None,
    away_team: str | None = None,
) -> dict | None:
    if not isinstance(rec, dict):
        return rec
    norm = dict(rec)

    ev_dec = None
    raw_ev = norm.get("ev")
    if raw_ev is not None:
        try:
            v = float(raw_ev)
            ev_dec = (v / 100.0) if abs(v) > 1.0 else v
        except Exception:
            ev_dec = None
    if ev_dec is None and norm.get("edge") is not None:
        try:
            edge_str = str(norm.get("edge")).replace("%", "").replace("+", "").strip()
            v = float(edge_str)
            ev_dec = v / 100.0
        except Exception:
            ev_dec = None
    if ev_dec is not None:
        norm["ev"] = round(ev_dec, 4)
        norm["ev_pct"] = round(ev_dec * 100.0, 2)
        if not norm.get("edge"):
            norm["edge"] = f"{ev_dec * 100.0:.1f}%"

    raw_conf = norm.get("confidence_0_100")
    if raw_conf is None:
        raw_conf = norm.get("confidence")
    conf_num = None
    conf_tier = norm.get("confidence_tier")
    if isinstance(raw_conf, (int, float)):
        v = float(raw_conf)
        conf_num = int(round(v * 100.0 if v <= 1.0 else v))
    elif isinstance(raw_conf, str):
        u = raw_conf.strip().upper()
        if u in ("HIGH", "MEDIUM", "MED", "LOW"):
            conf_tier = "MEDIUM" if u == "MED" else u
            conf_num = {"HIGH": 80, "MEDIUM": 62, "LOW": 45}[conf_tier]
        else:
            try:
                v = float(u.replace("%", ""))
                conf_num = int(round(v * 100.0 if v <= 1.0 else v))
            except Exception:
                conf_num = None

    if conf_tier is None and conf_num is not None:
        conf_tier = "HIGH" if conf_num >= 75 else ("MEDIUM" if conf_num >= 58 else "LOW")
    elif isinstance(conf_tier, str):
        conf_tier = "MEDIUM" if conf_tier.strip().upper() == "MED" else conf_tier.strip().upper()

    if conf_num is not None:
        norm["confidence_0_100"] = max(0, min(100, conf_num))
    if conf_tier in ("HIGH", "MEDIUM", "LOW"):
        norm["confidence_tier"] = conf_tier

    try:
        from src.utils.model_performance import compute_top6_quality_score, has_top6_risk_flag

        if "top6_eligible" not in norm:
            norm["top6_eligible"] = not has_top6_risk_flag(norm)
        if norm.get("quality_score") is None:
            norm["quality_score"] = compute_top6_quality_score(norm)
    except Exception:
        pass

    try:
        from src.utils.ev import compute_recommended_bet_size

        if norm.get("suggested_units") is None:
            sizing = compute_recommended_bet_size(
                norm.get("win_prob"),
                norm.get("price"),
                confidence_tier=norm.get("confidence_tier"),
                confidence_score=norm.get("confidence_0_100"),
                ev=norm.get("ev"),
                kelly_q=norm.get("kelly"),
            )
            norm["suggested_units"] = sizing["units"]
            norm["recommended_units"] = sizing["units"]
            norm["bankroll_pct"] = sizing["bankroll_pct"]
            norm["sizing_tier"] = sizing["sizing_tier"]
            if norm.get("kelly") is None:
                norm["kelly"] = sizing["kelly_fraction"]
    except Exception:
        pass

    try:
        if not isinstance(norm.get("bet_timing"), dict) or not norm["bet_timing"].get("action"):
            from src.utils.bet_timing import compute_bet_timing

            timing = compute_bet_timing(
                norm,
                start_time=start_time,
                home_team=home_team,
                away_team=away_team,
            )
            if timing is not None:
                norm["bet_timing"] = timing
    except Exception:
        pass

    return norm


def upsert_pick(date_et: str, event_id: str, res: dict, conn=None):
    # context_json is a JSON string currently in the model; store as JSONB if possible
    ctx = None
    try:
        cj = res.get('context_json') if isinstance(res, dict) else None
        if cj:
            ctx = json.loads(cj) if isinstance(cj, str) else cj
    except Exception:
        ctx = None

    rec = None
    try:
        raw_rec = (res.get('recommendations') or [None])[0]
        rec = _normalize_rec_for_storage(
            raw_rec,
            start_time=(res.get('start_time') if isinstance(res, dict) else None)
            or (ctx.get('start_time') if isinstance(ctx, dict) else None),
            home_team=(res.get('home_team') if isinstance(res, dict) else None)
            or (ctx.get('home_team') if isinstance(ctx, dict) else None),
            away_team=(res.get('away_team') if isinstance(res, dict) else None)
            or (ctx.get('away_team') if isinstance(ctx, dict) else None),
        )
    except Exception:
        rec = None

    is_actionable = bool(rec)
    reason = None
    if not is_actionable:
        raw_reason = (res.get('block_reason') or res.get('headline') or res.get('recommendation') or res.get('error') or 'No bet') if isinstance(res, dict) else 'No bet'
        r_str = str(raw_reason).strip()
        if ('Object of type' in r_str and 'serializable' in r_str) or ('Traceback' in r_str) :
            reason = 'Analysis unavailable — click Details to retry'
        else:
            reason = r_str[:300] or 'No bet'

    sql = """
    INSERT INTO daily_top_picks(date_et, event_id, league, computed_at, model_version, is_actionable, reason, rec_json, context_json)
    VALUES (%(d)s, %(eid)s, 'NCAAM', clock_timestamp(), %(mv)s, %(act)s, %(reason)s, %(rec)s::jsonb, %(ctx)s::jsonb)
    ON CONFLICT (date_et, event_id) DO UPDATE SET
      computed_at = EXCLUDED.computed_at,
      model_version = EXCLUDED.model_version,
      is_actionable = EXCLUDED.is_actionable,
      reason = EXCLUDED.reason,
      rec_json = EXCLUDED.rec_json,
      context_json = EXCLUDED.context_json
    WHERE NOT EXISTS (
      SELECT 1 FROM events e
      WHERE e.id = daily_top_picks.event_id
        AND e.start_time IS NOT NULL
        AND e.start_time <= (NOW() + INTERVAL '10 minutes')
    )
    """
    payload = {
        "d": date_et,
        "eid": event_id,
        "mv": res.get('model_version') if isinstance(res, dict) else None,
        "act": bool(is_actionable),
        "reason": reason,
        "rec": json.dumps(rec, default=str) if rec is not None else None,
        "ctx": json.dumps(ctx, default=str) if ctx is not None else None,
    }

    if conn is None:
        with get_db_connection() as conn2:
            _exec(conn2, sql, payload)
            conn2.commit()
    else:
        _exec(conn, sql, payload)


def archive_ev_observations(conn, event_id, result):
    for observation in result.get("ev_observations", []):
        params = {**observation, "event_id": event_id, "version": result["model_version"]}
        _exec(conn, """INSERT INTO ncaam_ev_observations
            (event_id,model_version,market,side,cohort,tip_at,quote_at,book,line,price,ev,ev_cutoff,win_prob)
            SELECT e.id,%(version)s,%(market)s,%(side)s,%(cohort)s,e.start_time,q.captured_at,
                   q.book,q.line_value,q.price,%(gate_ev)s,%(ev_cutoff)s,%(win_prob)s
            FROM events e JOIN LATERAL (
                SELECT * FROM odds_snapshots WHERE event_id=e.id AND market_type=%(market)s
                  AND side=upper(%(side)s) AND lower(book)=lower(%(book)s)
                  AND captured_at BETWEEN clock_timestamp()-interval '90 minutes' AND clock_timestamp()
                ORDER BY captured_at DESC,id DESC LIMIT 1
            ) q ON true WHERE e.id=%(event_id)s AND e.start_time>clock_timestamp()+interval '30 minutes'
              AND q.price=%(price)s AND q.line_value=%(line)s
            ON CONFLICT DO NOTHING""", params)


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

    days = int(os.getenv('TOP_PICKS_DAYS', '3'))
    event_rows = fetch_event_ids_for_date(date_et, limit_games=limit_games, days=days)
    print(f"events: {len(event_rows)} (days={days})")

    try:
        from src.utils.ncaam_season import season_start_date_for_game
        from src.database import init_bt_team_metrics_db
        from src.services.barttorvik import BartTorvikClient
        s_start = season_start_date_for_game(date_et)
        with get_db_connection() as conn:
            bt_cnt_row = _exec(conn, "SELECT COUNT(*) AS cnt FROM bt_team_metrics_daily WHERE date >= %s", (s_start,)).fetchone()
            bt_cnt = int(bt_cnt_row[0] if not isinstance(bt_cnt_row, dict) else bt_cnt_row.get("cnt", 0))
        if bt_cnt == 0:
            print("[build_daily_top_picks] bt_team_metrics_daily empty for current season; fetching Torvik ratings...")
            init_bt_team_metrics_db()
            BartTorvikClient().get_efficiency_ratings()
    except Exception as e:
        print(f"[build_daily_top_picks] Torvik check failed (continuing): {e}")

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
        for item in event_rows:
            eid, ev_day_et = item if isinstance(item, tuple) else (item, date_et)
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

                upsert_pick(ev_day_et, eid, res if isinstance(res, dict) else {}, conn=conn)
                archive_ev_observations(conn, eid, res or {})
                ok += 1
            except Exception as e:
                print(f"[build_daily_top_picks] error on {eid}: {e}")
                err += 1
                diag['errors'] += 1
                # still upsert a no-bet row with error reason
                try:
                    upsert_pick(ev_day_et, eid, {"recommendations": [], "error": str(e), "model_version": getattr(model, 'VERSION', None), "block_reason": "Analysis unavailable — click Details to retry"}, conn=conn)
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
