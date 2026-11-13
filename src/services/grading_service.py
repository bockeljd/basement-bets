import os
import sys
import json
from datetime import datetime, timedelta

# Add src to path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.database import get_db_connection, _exec, update_model_prediction_result, upsert_game_result
from src.parsers.espn_client import EspnClient
from src.services.odds_selection_service import OddsSelectionService
from src.action_network import get_todays_games
from src.services.grading_backfill import (
    _parse_dt_utc,
    extract_first_inning_totals,
    fetch_espn_scoreboard_finals,
    find_pending_backfill_dates,
    grade_nrfi_yrfi,
    grade_parlay_selection,
    grade_score_prediction,
    infer_market_type_and_line,
    ingest_mlb_finals_for_dates,
    match_mlb_schedule_game,
    match_team_names,
    parse_nrfi_yrfi_pick,
    resolve_team_side,
    void_stale_postponed_predictions,
)

# Load env variables if not already loaded
from dotenv import load_dotenv
load_dotenv()

class GradingService:
    def __init__(self):
        self.espn_client = EspnClient()
        self.odds_selector = OddsSelectionService()
        self._post_mortem_agent = None
        self._mlb_schedule_cache = {}

    @property
    def post_mortem_agent(self):
        if self._post_mortem_agent is None:
            try:
                from src.agents.post_mortem_agent import PostMortemAgent
                self._post_mortem_agent = PostMortemAgent()
            except Exception as e:
                print(f"[GRADING] PostMortemAgent unavailable: {e}")
                self._post_mortem_agent = False
        return self._post_mortem_agent or None

    def grade_predictions(
        self,
        *,
        backfill_days: int = 3,
        max_clv_rows: int = 250,
        max_grade_rows: int = 500,
        skip_clv: bool = False,
        backfill_pending: bool = False,
        include_all_ev: bool = True,
    ):
        """Grade pending predictions.

        IMPORTANT: This method can be invoked from a Vercel function (timeout-sensitive).
        Defaults are bounded, while `backfill_pending=True` discovers and grades historical
        ungraded prediction dates across NCAAM, MLB, NFL, NBA, and EPL.
        """
        print("[GRADING] Starting grading process...")
        self._mlb_schedule_cache = {}
        self._espn_parlay_cache = {}

        if backfill_pending and max_grade_rows < 5000:
            max_grade_rows = 5000

        # 0) Discover ungraded historical dates so missed slates self-heal cleanly
        pending_dates_by_league = {}
        try:
            max_pending_dates = 250 if backfill_pending else 10
            with get_db_connection() as conn:
                pending_dates_by_league = find_pending_backfill_dates(conn, max_dates=max_pending_dates)
        except Exception as e:
            print(f"[GRADING] Pending backfill date lookup warning: {e}")

        # 1) Update Game Results (Ingest latest + historical pending finals)
        active_leagues = ['NCAAM', 'MLB']
        for extra_lg in pending_dates_by_league.keys():
            if extra_lg not in active_leagues:
                active_leagues.append(extra_lg)

        scores_ingested = 0
        for league in active_leagues:
            scores_ingested += self._ingest_latest_scores(
                league,
                backfill_days=backfill_days,
                extra_dates=pending_dates_by_league.get(league, []),
            ) or 0

        # 2) Compute CLV for started games (bounded)
        clv_count = 0
        if not skip_clv:
            clv_lookback = max(int(backfill_days), 365) if backfill_pending else int(backfill_days)
            clv_count = self._compute_clv_for_started_games(
                max_rows=max_clv_rows,
                lookback_days=clv_lookback,
                include_all_ev=include_all_ev,
            )

        # 3) Grade outcomes for finals
        graded_count, graded_results = self._evaluate_db_predictions(
            max_rows=max_grade_rows,
            include_all_ev=include_all_ev,
        )

        # 3b) Void genuinely postponed/cancelled old events (>14d) after double-checking ESPN finals
        voided_count = 0
        if backfill_pending:
            try:
                with get_db_connection() as conn:
                    voided_count = void_stale_postponed_predictions(
                        conn,
                        max_age_days=14,
                        espn_cache=getattr(self, "_espn_parlay_cache", None),
                    )
                extra_graded, extra_results = self._evaluate_db_predictions(
                    max_rows=max_grade_rows,
                    include_all_ev=include_all_ev,
                )
                graded_count += extra_graded
                graded_results.extend(extra_results)
            except Exception as e:
                print(f"[GRADING] Stale postponement sweep warning: {e}")

        # 4) Run Post-Mortem pipeline on a small recent slice (never block historical sweeps)
        orphaned_results = self._fetch_unreflected_graded_results(
            backfill_days=backfill_days,
            include_all_ev=include_all_ev,
        )
        all_to_review = (graded_results[:10] + orphaned_results)[:15]

        if all_to_review and self.post_mortem_agent is not None:
            print(f"[GRADING] Triggering post-mortem for {len(all_to_review)} recent games...")
            try:
                self.post_mortem_agent.execute({"completed_games": all_to_review})
            except Exception as e:
                print(f"[GRADING] Post-mortem agent failed: {e}")

        return {
            "status": "Success",
            "graded": graded_count,
            "scores_ingested": scores_ingested,
            "clv_updates": clv_count,
            "skip_clv": bool(skip_clv),
            "backfill_days": int(backfill_days),
            "backfill_pending": bool(backfill_pending),
            "pending_dates_checked": sum(len(v) for v in pending_dates_by_league.values()),
        }

    def _ingest_latest_scores(
        self,
        league: str,
        *,
        backfill_days: int = 3,
        extra_dates: list | None = None,
    ) -> int:
        """Fetch final scores and upsert into game_results for recent + pending dates."""
        print(f"[GRADING] Fetching scores for {league}...")
        lg = str(league or '').upper().strip()

        eff_days = int(backfill_days if backfill_days is not None else os.getenv('GRADING_FINALS_BACKFILL_DAYS', '3'))
        date_set = {
            (datetime.now() - timedelta(days=d)).strftime("%Y-%m-%d")
            for d in range(0, max(0, eff_days) + 1)
        }
        for d_raw in (extra_dates or []):
            if d_raw:
                date_set.add(str(d_raw)[:10])
        dates_iso = sorted(date_set, reverse=True)
        dates_yyyymmdd = [d.replace('-', '') for d in dates_iso]

        if lg == 'MLB':
            try:
                from src.services.mlb_service import MLBService
                mlb_svc = MLBService()
                with get_db_connection() as conn:
                    mlb_count = ingest_mlb_finals_for_dates(
                        mlb_svc,
                        conn,
                        dates_iso,
                        schedule_cache=self._mlb_schedule_cache,
                    )
                print(f"[GRADING] Upserted {mlb_count} MLB finals from MLB Stats API")
                return int(mlb_count)
            except Exception as e:
                print(f"[GRADING] MLB Stats API ingestion error: {e}")
                return 0

        # Non-MLB leagues: load candidate events across the requested dates (+/- 2d buffer)
        known_event_ids = set()
        db_events = []
        try:
            min_d = min(dates_iso) if dates_iso else datetime.now().strftime("%Y-%m-%d")
            max_d = max(dates_iso) if dates_iso else min_d
            with get_db_connection() as conn:
                rows = _exec(
                    conn,
                    """
                    SELECT e.id, e.home_team, e.away_team, e.start_time, COALESCE(gr.final, FALSE) AS has_final
                    FROM events e
                    LEFT JOIN game_results gr ON gr.event_id = e.id
                    WHERE UPPER(COALESCE(e.league, '')) = %(league)s
                      AND (e.start_time AT TIME ZONE 'America/New_York')::date
                          BETWEEN (%(min_d)s::date - INTERVAL '2 days') AND (%(max_d)s::date + INTERVAL '2 days')
                    """,
                    {"league": lg, "min_d": min_d, "max_d": max_d},
                ).fetchall()
                for r in rows:
                    row_d = dict(r)
                    known_event_ids.add(row_d['id'])
                    db_events.append(row_d)
        except Exception as e:
            print(f"[GRADING] Warning: could not prefetch {lg} events: {e}")

        upserted_event_ids = set()
        count = 0

        # 1) Action Network primary for NCAAM (v2 division=D1) and NFL/NBA/EPL (v1)
        if lg == 'NCAAM':
            import requests

            headers = {
                'Authority': 'api.actionnetwork.com',
                'Accept': 'application/json',
                'Origin': 'https://www.actionnetwork.com',
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36'
            }

            def fetch_v2(date_str: str):
                url = "https://api.actionnetwork.com/web/v2/scoreboard/ncaab"
                params = {
                    "bookIds": "15,30,79,2988,75,123,71,68,69",
                    "periods": "event",
                    "date": date_str,
                    "division": "D1",
                }
                resp = requests.get(url, params=params, headers=headers, timeout=20)
                resp.raise_for_status()
                return resp.json()

            seen_game_ids = set()
            for date_str in dates_yyyymmdd:
                try:
                    dt0 = datetime.strptime(date_str, "%Y%m%d")
                    date_next = (dt0 + timedelta(days=1)).strftime("%Y%m%d")
                    for qd in (date_str, date_next):
                        data = fetch_v2(qd)
                        for g in (data.get('games', []) or []):
                            gid = g.get('id')
                            if gid is None:
                                continue
                            gid = str(gid)
                            if gid in seen_game_ids:
                                continue
                            status = str(g.get('status') or '').lower().strip()
                            if status not in ('complete', 'completed', 'closed', 'final'):
                                continue
                            box = g.get('boxscore') or {}
                            home_score = box.get('total_home_points')
                            away_score = box.get('total_away_points')
                            if home_score is None or away_score is None:
                                continue
                            event_id = f"action:ncaam:{gid}"
                            if known_event_ids and event_id not in known_event_ids:
                                continue
                            seen_game_ids.add(gid)
                            upsert_game_result({
                                "event_id": event_id,
                                "home_score": int(home_score),
                                "away_score": int(away_score),
                                "final": True,
                                "period": "FINAL",
                            })
                            upserted_event_ids.add(event_id)
                            count += 1
                except Exception as e:
                    print(f"[GRADING] Action Network v2 error fetching NCAAM {date_str}: {e}")
            print(f"[GRADING] Upserted {count} NCAAM finals from Action Network v2")

        # 2) ESPN Scoreboard fallback for events still missing final game_results
        missing_events = [
            ev for ev in db_events
            if not ev.get('has_final') and ev['id'] not in upserted_event_ids
        ]
        if missing_events and lg in ('NCAAM', 'NFL', 'NBA', 'EPL'):
            espn_count = 0
            espn_dates = set()
            for ev in missing_events:
                st = _parse_dt_utc(ev.get('start_time'))
                if st:
                    espn_dates.add(st.strftime("%Y%m%d"))
                    espn_dates.add((st - timedelta(days=1)).strftime("%Y%m%d"))
            if not espn_dates:
                espn_dates = set(dates_yyyymmdd)

            espn_games = []
            for d_str in sorted(espn_dates):
                espn_games.extend(fetch_espn_scoreboard_finals(lg, d_str))

            for ev in missing_events:
                ev_dt = _parse_dt_utc(ev.get('start_time'))
                for eg in espn_games:
                    if not (
                        match_team_names(ev.get('home_team'), eg.get('home_team'), is_mlb=False)
                        and match_team_names(ev.get('away_team'), eg.get('away_team'), is_mlb=False)
                    ):
                        continue
                    eg_dt = _parse_dt_utc(eg.get('start_time'))
                    if ev_dt and eg_dt and abs((ev_dt - eg_dt).total_seconds()) > 36 * 3600:
                        continue
                    upsert_game_result({
                        "event_id": ev['id'],
                        "home_score": int(eg['home_score']),
                        "away_score": int(eg['away_score']),
                        "final": True,
                        "period": "FINAL",
                    })
                    upserted_event_ids.add(ev['id'])
                    espn_count += 1
                    count += 1
                    break
            if espn_count:
                print(f"[GRADING] Upserted {espn_count} {lg} finals from ESPN fallback")

        return count

    def _compute_clv_for_started_games(self, *, max_rows: int = 250, lookback_days: int = 3, include_all_ev: bool = True):
        """Compute CLV for games that have started.

        This version is DB-driven and side-aware so it actually fills close_line/close_price
        for recommended bets.

        Bounded for serverless execution.
        """
        min_ev = float(os.getenv('GRADING_MIN_EV_PER_UNIT', '0.02'))
        ev_clause = "" if include_all_ev else "AND COALESCE(m.ev_per_unit, 0) >= %(min_ev)s"

        # DB-driven batch update using LATERAL to pick the last snapshot before tip.
        # This avoids per-row connections and makes CLV usable.
        upd_q = f"""
        WITH candidates AS (
          SELECT
            m.id,
            m.event_id,
            m.market_type,
            m.pick,
            COALESCE(m.open_line, m.bet_line) as open_line,
            COALESCE(m.open_price, m.bet_price, m.price) as open_price,
            e.start_time,
            e.home_team,
            e.away_team,
            CASE
              WHEN m.market_type='TOTAL' AND UPPER(m.pick) IN ('OVER','UNDER') THEN UPPER(m.pick)
              WHEN m.market_type IN ('SPREAD','MONEYLINE') AND m.pick = e.home_team THEN 'HOME'
              WHEN m.market_type IN ('SPREAD','MONEYLINE') AND m.pick = e.away_team THEN 'AWAY'
              WHEN m.market_type IN ('SPREAD','MONEYLINE') AND LOWER(m.pick)='home' THEN 'HOME'
              WHEN m.market_type IN ('SPREAD','MONEYLINE') AND LOWER(m.pick)='away' THEN 'AWAY'
              ELSE NULL
            END as side
          FROM model_predictions m
          JOIN events e ON e.id=m.event_id
          WHERE (
              (m.market_type IN ('SPREAD','TOTAL') AND m.close_line IS NULL)
              OR (m.market_type='MONEYLINE' AND m.close_price IS NULL)
            )
            AND e.start_time < CURRENT_TIMESTAMP
            AND e.start_time > (CURRENT_TIMESTAMP - (%(d)s || ' days')::interval)
            {ev_clause}
            AND m.market_type IN ('SPREAD','TOTAL','MONEYLINE')
            AND UPPER(COALESCE(m.market_type,'')) <> 'AUTO'
            AND m.pick IS NOT NULL
            AND TRIM(m.pick) <> ''
            AND UPPER(TRIM(m.pick)) NOT IN ('NONE', 'NO BET', 'PASS')
            AND m.selection IS NOT NULL
            AND TRIM(m.selection) <> ''
            AND m.selection <> '—'
            -- ignore last-second analyses (shouldn't be considered "published" recs)
            AND m.analyzed_at <= (e.start_time - INTERVAL '10 minutes')
          ORDER BY e.start_time DESC
          LIMIT %(lim)s
        ), snaps AS (
          SELECT
            c.id as mid,
            c.market_type,
            c.pick,
            c.open_line,
            c.open_price,
            s.line_value,
            s.price,
            s.captured_at
          FROM candidates c
          JOIN LATERAL (
            SELECT line_value, price, captured_at
            FROM odds_snapshots
            WHERE event_id=c.event_id
              AND market_type=c.market_type
              AND side=c.side
              AND captured_at <= c.start_time
              AND (
                (c.market_type IN ('SPREAD','TOTAL') AND line_value IS NOT NULL)
                OR (c.market_type='MONEYLINE' AND price IS NOT NULL AND price != 0)
              )
            ORDER BY captured_at DESC
            LIMIT 1
          ) s ON TRUE
          WHERE c.side IS NOT NULL
        ), computed AS (
          SELECT
            mid,
            market_type,
            line_value,
            price,
            captured_at,
            CASE
              WHEN market_type='SPREAD' THEN (open_line - line_value)
              WHEN market_type='TOTAL' AND UPPER(pick)='OVER' THEN (line_value - open_line)
              WHEN market_type='TOTAL' AND UPPER(pick)='UNDER' THEN (open_line - line_value)
              WHEN market_type='MONEYLINE' AND open_price IS NOT NULL AND open_price != 0 AND price IS NOT NULL AND price != 0 THEN
                ROUND(
                  ((
                    (CASE WHEN price < 0 THEN (-price)::double precision / ((-price)::double precision + 100.0)
                          ELSE 100.0 / (price::double precision + 100.0) END)
                    -
                    (CASE WHEN open_price < 0 THEN (-open_price)::double precision / ((-open_price)::double precision + 100.0)
                          ELSE 100.0 / (open_price::double precision + 100.0) END)
                  ) * 100.0)::numeric,
                  2
                )::double precision
              ELSE NULL
            END as clv_val
          FROM snaps
        )
        UPDATE model_predictions m
        SET
          close_line = CASE WHEN c.market_type IN ('SPREAD','TOTAL') THEN c.line_value ELSE m.close_line END,
          close_price = c.price,
          close_captured_at = c.captured_at,
          clv_method = CASE WHEN c.market_type='MONEYLINE' THEN 'odds_snapshot_ml_prob_before_tip' ELSE 'odds_snapshot_before_tip' END,
          clv_points = c.clv_val
        FROM computed c
        WHERE m.id=c.mid
        """

        with get_db_connection() as conn:
            cur = _exec(conn, upd_q, {"d": int(lookback_days), "lim": int(max_rows), "min_ev": float(min_ev)})
            conn.commit()
            return int(cur.rowcount or 0)

    def _evaluate_db_predictions(self, *, max_rows: int = 500, include_all_ev: bool = True):
        """Grade outcomes for pending predictions where the game is FINAL."""
        min_ev = float(os.getenv('GRADING_MIN_EV_PER_UNIT', '0.02'))
        ev_clause = "" if include_all_ev else "AND COALESCE(m.ev_per_unit, 0) >= %(min_ev)s"
        query = f"""
        SELECT m.id, m.event_id, m.market_type, m.pick, m.bet_line, m.book,
               m.selection, m.analyzed_at, m.narrative_json, m.ev_per_unit,
               e.league, e.home_team, e.away_team, e.start_time,
               gr.home_score, gr.away_score, gr.final
        FROM model_predictions m
        JOIN events e ON m.event_id = e.id
        LEFT JOIN game_results gr ON e.id = gr.event_id
        WHERE (UPPER(COALESCE(m.outcome, 'PENDING')) IN ('PENDING', 'VOID', ''))
          AND (
              gr.final = TRUE
              OR (UPPER(COALESCE(m.market_type, '')) = 'PARLAY' AND e.start_time < CURRENT_TIMESTAMP - INTERVAL '6 hours')
              OR (gr.home_score IS NOT NULL AND gr.away_score IS NOT NULL AND e.start_time < CURRENT_TIMESTAMP - INTERVAL '8 hours')
          )
          AND e.start_time < CURRENT_TIMESTAMP
          {ev_clause}
          AND UPPER(COALESCE(NULLIF(TRIM(m.pick), ''), NULLIF(TRIM(m.selection), ''), '')) NOT IN ('', 'NONE', 'NO BET', 'PASS')
          AND m.selection IS NOT NULL
          AND TRIM(m.selection) <> ''
          AND m.selection NOT IN ('—', '-')
        ORDER BY e.start_time DESC, m.analyzed_at DESC
        LIMIT %(lim)s
        """

        with get_db_connection() as conn:
            rows = _exec(conn, query, {"lim": int(max_rows), "min_ev": float(min_ev)}).fetchall()

        print(f"[GRADING] Found {len(rows)} pending bets with final scores.")

        graded_results = []
        graded = 0
        for row in rows:
            try:
                row_dict = dict(row)
                outcome = self._grade_row(row_dict)
                if outcome != 'PENDING':
                    graded_results.append({
                        "away_team": row_dict['away_team'],
                        "home_team": row_dict['home_team'],
                        "away_score": row_dict['away_score'],
                        "home_score": row_dict['home_score'],
                        "oracle_prediction": row_dict.get('oracle_verdict') or row_dict.get('narrative_json') or "N/A",
                        "recommended_bet": row_dict.get('selection') or f"{row_dict['pick']} {row_dict['bet_line']}",
                        "actual_result": f"{row_dict['home_team']} {row_dict['home_score']} - {row_dict['away_team']} {row_dict['away_score']}",
                        "game_date": row_dict.get('start_time').strftime("%Y-%m-%d") if row_dict.get('start_time') else (row_dict.get('analyzed_at').strftime("%Y-%m-%d") if row_dict.get('analyzed_at') else None),
                        "final": row_dict.get('final')
                    })
                    update_model_prediction_result(row['id'], outcome)
                    graded += 1
            except Exception as e:
                print(f"[GRADING] Error grading row {row['id']}: {e}")

        return graded, graded_results

    def _fetch_unreflected_graded_results(self, backfill_days: int = 3, include_all_ev: bool = True) -> list:
        """Fetch games that are GRADED but have no entry in agent_memories yet."""
        min_ev = float(os.getenv('GRADING_MIN_EV_PER_UNIT', '0.02'))
        ev_clause = "" if include_all_ev else "AND COALESCE(m.ev_per_unit, 0) >= %(min_ev)s"
        query = f"""
        SELECT m.id, m.event_id, m.market_type, m.pick, m.bet_line, m.book,
               m.selection, m.analyzed_at, m.narrative_json,
               e.home_team, e.away_team, e.start_time,
               gr.home_score, gr.away_score, gr.final
        FROM model_predictions m
        JOIN events e ON m.event_id = e.id
        JOIN game_results gr ON e.id = gr.event_id
        LEFT JOIN agent_memories am ON (am.team_a = e.away_team AND am.team_b = e.home_team)
        WHERE m.outcome <> 'PENDING'
          AND m.outcome IS NOT NULL
          AND m.outcome <> 'VOID'
          AND gr.final = TRUE
          AND am.id IS NULL
          AND e.start_time >= (NOW() - (%(days)s || ' days')::interval)
          {ev_clause}
        ORDER BY m.analyzed_at DESC
        LIMIT 20
        """
        results = []
        try:
            with get_db_connection() as conn:
                rows = _exec(conn, query, {"days": backfill_days, "min_ev": min_ev}).fetchall()
                for row in rows:
                    row_dict = dict(row)
                    results.append({
                        "away_team": row_dict['away_team'],
                        "home_team": row_dict['home_team'],
                        "away_score": row_dict['away_score'],
                        "home_score": row_dict['home_score'],
                        "oracle_prediction": row_dict.get('oracle_verdict') or row_dict.get('narrative_json') or "N/A",
                        "recommended_bet": row_dict.get('selection') or f"{row_dict['pick']} {row_dict['bet_line']}",
                        "actual_result": f"{row_dict['home_team']} {row_dict['home_score']} - {row_dict['away_team']} {row_dict['away_score']}",
                        "game_date": row_dict.get('start_time').strftime("%Y-%m-%d") if row_dict.get('start_time') else (row_dict.get('analyzed_at').strftime("%Y-%m-%d") if row_dict.get('analyzed_at') else None),
                        "final": row_dict.get('final')
                    })
        except Exception as e:
            print(f"[GRADING] Error pre-fetching orphaned reflections: {e}")
            
        return results

    def _get_cached_mlb_schedule(self, date_str: str) -> list:
        """Return MLB Stats API schedule for YYYY-MM-DD using an in-memory per-run cache."""
        if not hasattr(self, '_mlb_schedule_cache') or self._mlb_schedule_cache is None:
            self._mlb_schedule_cache = {}
        if date_str not in self._mlb_schedule_cache:
            from src.services.mlb_service import MLBService
            self._mlb_schedule_cache[date_str] = MLBService().get_schedule(date_str) or []
        return self._mlb_schedule_cache[date_str]

    def _grade_row(self, row):
        pick = row.get('pick')
        selection = row.get('selection')
        pick_u = str(pick or '').strip().upper()
        sel_u = str(selection or '').strip().upper()

        # Guardrails: ignore non-bet / placeholder predictions cleanly.
        if pick_u in ('NONE', 'NO BET', 'PASS') or sel_u in ('NONE', 'NO BET', 'PASS'):
            return 'VOID'
        if not pick_u and not sel_u:
            return 'VOID'

        market, _ = infer_market_type_and_line(
            row.get('market_type'),
            pick=pick,
            selection=selection,
            bet_line=row.get('bet_line'),
        )
        if market not in ('SPREAD', 'TOTAL', 'MONEYLINE', 'NRFI', 'YRFI', 'PARLAY'):
            return 'VOID'

        h_score = row.get('home_score')
        a_score = row.get('away_score')
        if market != 'PARLAY' and (h_score is None or a_score is None):
            return 'PENDING'

        is_mlb = (
            str(row.get('league') or '').upper() == 'MLB'
            or str(row.get('event_id') or '').startswith(('mlb:', 'action:mlb:'))
            or market in ('NRFI', 'YRFI')
        )

        if market in ('SPREAD', 'TOTAL', 'MONEYLINE'):
            return grade_score_prediction(
                market_type=market,
                pick=pick,
                selection=selection,
                bet_line=row.get('bet_line'),
                home_team=row.get('home_team'),
                away_team=row.get('away_team'),
                home_score=h_score,
                away_score=a_score,
                is_mlb=is_mlb,
            )

        if market == 'PARLAY':
            ref_time = row.get('start_time') or row.get('analyzed_at')
            return self._grade_parlay(
                selection or pick,
                ref_time=ref_time,
                league=str(row.get('league') or 'NCAAM'),
            )

        if market in ('NRFI', 'YRFI'):
            nrfi_kind = parse_nrfi_yrfi_pick(pick, selection=selection)
            if not nrfi_kind:
                return 'VOID'
            try:
                event_id = str(row.get('event_id') or '')
                start_dt = _parse_dt_utc(row.get('start_time') or row.get('analyzed_at'))

                # 1) Match via MLB schedule (with cached linescores) across start_dt +/- 1d
                matched_game = None
                if start_dt and row.get('home_team') and row.get('away_team'):
                    candidate_games = []
                    for delta in (0, -1, 1):
                        d_str = (start_dt + timedelta(days=delta)).strftime("%Y-%m-%d")
                        candidate_games.extend(self._get_cached_mlb_schedule(d_str))
                    matched_game = match_mlb_schedule_game(
                        candidate_games,
                        row.get('away_team'),
                        row.get('home_team'),
                        start_time=start_dt,
                        require_final=False,
                    )

                if matched_game:
                    first_inn = extract_first_inning_totals(matched_game)
                    if first_inn is not None:
                        return grade_nrfi_yrfi(pick, first_inn[0], first_inn[1], selection=selection)
                    matched_pk = matched_game.get('game_pk')
                    if matched_pk:
                        from src.services.mlb_service import MLBService
                        fi = MLBService().get_first_inning_scores(int(matched_pk))
                        if fi and fi.get('away_1st') is not None and fi.get('home_1st') is not None:
                            return grade_nrfi_yrfi(pick, fi['away_1st'], fi['home_1st'], selection=selection)

                # 2) Direct MLB Stats game_pk lookup only when event_id is native mlb:{game_pk}
                if event_id.startswith('mlb:'):
                    tail = event_id.split(':')[-1]
                    if tail.isdigit():
                        from src.services.mlb_service import MLBService
                        fi = MLBService().get_first_inning_scores(int(tail))
                        if fi and fi.get('away_1st') is not None and fi.get('home_1st') is not None:
                            return grade_nrfi_yrfi(pick, fi['away_1st'], fi['home_1st'], selection=selection)
            except Exception as e:
                print(f"[GRADING] NRFI grading error: {e}")
            return 'PENDING'

        return 'VOID'

    def _grade_parlay(self, selection: str, ref_time=None, league: str = 'NCAAM') -> str:
        """Grade a parlay against game_results near the event date, falling back to ESPN scoreboard."""
        if not selection or ('parlay' not in str(selection).lower() and '|' not in str(selection)):
            return 'PENDING'
        with get_db_connection() as conn:
            return grade_parlay_selection(
                conn,
                selection,
                ref_time=ref_time,
                league=league,
                espn_cache=getattr(self, '_espn_parlay_cache', None),
            )

if __name__ == "__main__":
    service = GradingService()
    res = service.grade_predictions()
    print(res)
