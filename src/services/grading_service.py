import os
import sys
import json
from datetime import datetime, timedelta

# Add src to path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from database import get_db_connection, _exec, update_model_prediction_result, upsert_game_result
from parsers.espn_client import EspnClient
from services.odds_selection_service import OddsSelectionService
from src.action_network import get_todays_games
from src.agents.post_mortem_agent import PostMortemAgent
from src.utils.naming import standardize_team_name

# Load env variables if not already loaded
from dotenv import load_dotenv
load_dotenv()

class GradingService:
    def __init__(self):
        self.espn_client = EspnClient()
        self.odds_selector = OddsSelectionService()
        self.post_mortem_agent = PostMortemAgent()

    def grade_predictions(self, *, backfill_days: int = 3, max_clv_rows: int = 250, max_grade_rows: int = 500, skip_clv: bool = False):
        """Grade pending predictions.

        IMPORTANT: This method can be invoked from a Vercel function (timeout-sensitive).
        Defaults are intentionally bounded.
        """
        print("[GRADING] Starting grading process...")

        # 1) Update Game Results (Ingest latest finals)
        # NOTE: We currently grade NCAAM using Action Network as the source of truth.
        active_leagues = ['NCAAM']
        for league in active_leagues:
            self._ingest_latest_scores(league)

        # 2) Compute CLV for started games (bounded)
        clv_count = 0
        if not skip_clv:
            clv_count = self._compute_clv_for_started_games(max_rows=max_clv_rows, lookback_days=backfill_days)

        # 3) Grade outcomes for finals (bounded)
        graded_count, graded_results = self._evaluate_db_predictions(max_rows=max_grade_rows)

        # 4) Run Post-Mortem pipeline on recently graded AND orphaned graded games
        orphaned_results = self._fetch_unreflected_graded_results(backfill_days=backfill_days)
        all_to_review = graded_results + orphaned_results

        if all_to_review:
            print(f"[GRADING] Triggering post-mortem for {len(all_to_review)} games ({len(graded_results)} new, {len(orphaned_results)} orphaned)...")
            try:
                self.post_mortem_agent.execute({"completed_games": all_to_review})
            except Exception as e:
                print(f"[GRADING] Post-mortem agent failed: {e}")

        return {"status": "Success", "graded": graded_count, "clv_updates": clv_count, "skip_clv": bool(skip_clv), "backfill_days": backfill_days}

    def _ingest_latest_scores(self, league):
        """Fetch scores and upsert to game_results.

        Primary goal: keep grading unblocked.

        - For NCAAM: prefer Action Network (our events are action:ncaam:* so matching is clean).
        - For other leagues: keep ESPN for now.
        """
        print(f"[GRADING] Fetching scores for {league}...")

        # Backfill window: history tab can include older games; keep this reasonably small
        # to avoid heavy API usage.
        backfill_days = int(os.getenv('GRADING_FINALS_BACKFILL_DAYS', '3'))
        dates = [
            (datetime.now() - timedelta(days=d)).strftime("%Y%m%d")
            for d in range(0, backfill_days + 1)
        ]

        # 1) Action Network primary (NCAAM)
        if league == 'NCAAM':
            # Cache the set of known event ids so we don't violate FK constraints in game_results.
            known_event_ids = set()
            try:
                with get_db_connection() as conn:
                    rows = _exec(
                        conn,
                        """
                        SELECT id
                        FROM events
                        WHERE league = 'NCAAM'
                          AND id LIKE 'action:ncaam:%%'
                          AND start_time >= (NOW() - (%(days)s || ' days')::interval)
                        """,
                        {"days": backfill_days + 2},
                    ).fetchall()
                    known_event_ids = {r['id'] for r in rows}
            except Exception as e:
                print(f"[GRADING] Warning: could not prefetch known NCAAM Action event ids: {e}")

            # IMPORTANT: web/v1 scoreboard returns only a small subset of games.
            # Use web/v2 scoreboard + division=D1 to cover the full slate.
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

            count = 0
            seen_game_ids = set()

            for date_str in dates:
                try:
                    # Query both date and next day to catch late-night ET games.
                    try:
                        dt0 = datetime.strptime(date_str, "%Y%m%d")
                        date_next = (dt0 + timedelta(days=1)).strftime("%Y%m%d")
                    except Exception:
                        date_next = None

                    query_dates = [date_str] + ([date_next] if date_next else [])

                    for qd in query_dates:
                        data = fetch_v2(qd)
                        games = data.get('games', []) or []
                        for g in games:
                            gid = g.get('id')
                            if gid is None:
                                continue
                            gid = str(gid)
                            if gid in seen_game_ids:
                                continue

                            status = str(g.get('status') or '').lower().strip()
                            # v2 uses 'complete' when final
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
                            count += 1
                except Exception as e:
                    print(f"[GRADING] Action Network v2 error fetching NCAAM {date_str}: {e}")

            print(f"[GRADING] Upserted {count} NCAAM finals from Action Network v2")

        # 2) ESPN fallback (DISABLED)
        return

    def _compute_clv_for_started_games(self, *, max_rows: int = 250, lookback_days: int = 3):
        """Compute CLV for games that have started.

        This version is DB-driven and side-aware so it actually fills close_line/close_price
        for recommended bets.

        Bounded for serverless execution.
        """
        min_ev = float(os.getenv('GRADING_MIN_EV_PER_UNIT', '0.02'))

        # DB-driven batch update using LATERAL to pick the last snapshot before tip.
        # This avoids per-row connections and makes CLV usable.
        upd_q = """
        WITH candidates AS (
          SELECT
            m.id,
            m.event_id,
            m.market_type,
            m.pick,
            COALESCE(m.open_line, m.bet_line) as open_line,
            COALESCE(m.open_price, m.bet_price) as open_price,
            e.start_time,
            e.home_team,
            e.away_team,
            CASE
              WHEN m.market_type='TOTAL' AND UPPER(m.pick) IN ('OVER','UNDER') THEN UPPER(m.pick)
              WHEN m.market_type='SPREAD' AND m.pick = e.home_team THEN 'HOME'
              WHEN m.market_type='SPREAD' AND m.pick = e.away_team THEN 'AWAY'
              WHEN m.market_type='SPREAD' AND LOWER(m.pick)='home' THEN 'HOME'
              WHEN m.market_type='SPREAD' AND LOWER(m.pick)='away' THEN 'AWAY'
              ELSE NULL
            END as side
          FROM model_predictions m
          JOIN events e ON e.id=m.event_id
          WHERE m.close_line IS NULL
            AND e.start_time < CURRENT_TIMESTAMP
            AND e.start_time > (CURRENT_TIMESTAMP - (%(d)s || ' days')::interval)
            -- Recommended bets only (publication gates / non-placeholder)
            AND COALESCE(m.ev_per_unit, 0) >= %(min_ev)s
            AND m.market_type IN ('SPREAD','TOTAL')
            AND UPPER(COALESCE(m.market_type,'')) <> 'AUTO'
            AND m.pick IS NOT NULL
            AND TRIM(m.pick) <> ''
            AND UPPER(TRIM(m.pick)) <> 'NONE'
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
            ORDER BY captured_at DESC
            LIMIT 1
          ) s ON TRUE
          WHERE c.side IS NOT NULL
            AND s.line_value IS NOT NULL
        )
        UPDATE model_predictions m
        SET
          close_line = s.line_value,
          close_price = s.price,
          close_captured_at = s.captured_at,
          clv_method = 'odds_snapshot_before_tip',
          clv_points = CASE
            WHEN m.market_type='SPREAD' THEN (COALESCE(m.open_line, m.bet_line) - s.line_value)
            WHEN m.market_type='TOTAL' AND UPPER(m.pick)='OVER' THEN (s.line_value - COALESCE(m.open_line, m.bet_line))
            WHEN m.market_type='TOTAL' AND UPPER(m.pick)='UNDER' THEN (COALESCE(m.open_line, m.bet_line) - s.line_value)
            ELSE NULL
          END
        FROM snaps s
        WHERE m.id=s.mid
        """

        with get_db_connection() as conn:
            cur = _exec(conn, upd_q, {"d": int(lookback_days), "lim": int(max_rows), "min_ev": float(min_ev)})
            conn.commit()
            return int(cur.rowcount or 0)

    def _evaluate_db_predictions(self, *, max_rows: int = 500):
        """Grade outcomes for pending predictions where the game is FINAL.

        Bounded for serverless execution.
        """
        min_ev = float(os.getenv('GRADING_MIN_EV_PER_UNIT', '0.02'))
        query = """
        SELECT m.id, m.market_type, m.pick, m.bet_line, m.book,
               m.selection, m.analyzed_at, m.narrative_json,
               e.home_team, e.away_team, e.start_time,
               gr.home_score, gr.away_score, gr.final
        FROM model_predictions m
        JOIN events e ON m.event_id = e.id
        JOIN game_results gr ON e.id = gr.event_id
        WHERE (m.outcome = 'PENDING' OR m.outcome IS NULL OR m.outcome = 'VOID')
          AND gr.final = TRUE
          AND e.start_time < CURRENT_TIMESTAMP
          AND COALESCE(m.ev_per_unit, 0) >= %(min_ev)s
          AND m.market_type IS NOT NULL
          AND UPPER(m.market_type) <> 'AUTO'
          AND m.pick IS NOT NULL
          AND UPPER(m.pick) <> 'NONE'
          AND m.selection IS NOT NULL
          AND TRIM(m.selection) <> ''
          AND m.selection <> '—'
        ORDER BY m.analyzed_at DESC
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
                    # Add to results for post-mortem
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
                    from src.database import update_model_prediction_result
                    update_model_prediction_result(row['id'], outcome)
                    graded += 1
            except Exception as e:
                print(f"[GRADING] Error grading row {row['id']}: {e}")
                
        return graded, graded_results

    def _fetch_unreflected_graded_results(self, backfill_days: int = 3) -> list:
        """Fetch games that are GRADED but have no entry in agent_memories yet.
        This provides a safety net if a post-mortem run failed or timed out.
        """
        min_ev = float(os.getenv('GRADING_MIN_EV_PER_UNIT', '0.02'))
        query = """
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
          AND COALESCE(m.ev_per_unit, 0) >= %(min_ev)s
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

    def _grade_row(self, row):
        from src.utils.normalize import normalize_market
        market = normalize_market(row['market_type'])
        pick = row['pick']
        line = float(row['bet_line']) if row['bet_line'] is not None else 0.0

        # Normalize spread picks that are stored as HOME/AWAY to actual team names
        # so we don't incorrectly mark them VOID.
        if market == 'SPREAD' and pick is not None:
            p = str(pick).strip().upper()
            if p in ('HOME', 'H'):
                pick = row.get('home_team')
            elif p in ('AWAY', 'A'):
                pick = row.get('away_team')

        # Guardrails: ignore placeholder/auto predictions so they don't clog Pending.
        if not pick or str(pick).upper() == 'NONE':
            return 'VOID'
        if market not in ('SPREAD', 'TOTAL', 'MONEYLINE'):
            return 'VOID'
        
        h_score = row['home_score']
        a_score = row['away_score']
        
        outcome = 'PENDING'
        
        if market == 'SPREAD':
            # Robust side matching with standardization and substring fallback
            s_pick = standardize_team_name(str(pick)).lower()
            s_home = standardize_team_name(str(row['home_team'])).lower()
            s_away = standardize_team_name(str(row['away_team'])).lower()

            if s_pick == s_home or s_pick in s_home or s_home in s_pick:
                score = h_score
                opp_score = a_score
            elif s_pick == s_away or s_pick in s_away or s_away in s_pick:
                score = a_score
                opp_score = h_score
            else:
                return 'VOID'
            
            if score + line > opp_score: outcome = 'WON'
            elif score + line < opp_score: outcome = 'LOST'
            else: outcome = 'PUSH'
            
        elif market == 'TOTAL':
            total_score = h_score + a_score
            if str(pick).upper() == 'OVER':
                outcome = 'WON' if total_score > line else 'LOST' if total_score < line else 'PUSH'
            elif str(pick).upper() == 'UNDER':
                outcome = 'WON' if total_score < line else 'LOST' if total_score > line else 'PUSH'
                
        elif market == 'MONEYLINE':
            s_pick = standardize_team_name(str(pick)).lower()
            s_home = standardize_team_name(str(row['home_team'])).lower()
            s_away = standardize_team_name(str(row['away_team'])).lower()

            if s_pick == s_home or s_pick in s_home or s_home in s_pick:
                outcome = 'WON' if h_score > a_score else 'LOST'
            elif s_pick == s_away or s_pick in s_away or s_away in s_pick:
                outcome = 'WON' if a_score > h_score else 'LOST'
            else:
                return 'VOID'
            
        return outcome

if __name__ == "__main__":
    service = GradingService()
    res = service.grade_predictions()
    print(res)
