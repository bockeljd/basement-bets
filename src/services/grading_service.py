import os
import sys
import json
from datetime import datetime, timedelta

# Add src to path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from database import get_db_connection, _exec, update_model_prediction_result, upsert_game_result
from parsers.espn_client import EspnClient
from services.odds_selection_service import OddsSelectionService

# Load env variables if not already loaded
from dotenv import load_dotenv
load_dotenv()

class GradingService:
    def __init__(self):
        self.espn_client = EspnClient()
        self.odds_selector = OddsSelectionService()

    def grade_predictions(self):
        """
        Main method to Grade 'Pending' predictions.
        Now includes CLV computation and outcome grading.
        """
        print("[GRADING] Starting grading process...")
        
        # 1. Update Game Results (Ingest latest scores)
        active_leagues = ['NCAAM', 'NBA', 'NFL', 'NCAAF', 'EPL'] 
        for league in active_leagues:
            self._ingest_latest_scores(league)

        # 2. Compute CLV for Started Games (that haven't been CLV-graded yet)
        clv_count = self._compute_clv_for_started_games()
        
        # 3. Grade Outcomes for Final Games
        graded_count = self._evaluate_db_predictions()
        
        return {"status": "Success", "graded": graded_count, "clv_updates": clv_count}

    def _ingest_latest_scores(self, league):
        """
        Fetch scores from ESPN and upsert to game_results table.
        """
        print(f"[GRADING] Fetching scores for {league}...")
        dates = [
            (datetime.now() - timedelta(days=1)).strftime("%Y%m%d"),
            datetime.now().strftime("%Y%m%d")
        ]
        
        count = 0
        for date_str in dates:
            try:
                events = self.espn_client.fetch_scoreboard(league, date_str)
                for ev in events:
                    if ev['status'] in ['STATUS_FINAL', 'final', 'complete', 'completed']:
                        res_data = {
                            "event_id": ev['id'],
                            "home_score": int(ev['home_score']) if ev.get('home_score') is not None else 0,
                            "away_score": int(ev['away_score']) if ev.get('away_score') is not None else 0,
                            "final": True,
                            "period": "FINAL"
                        }
                        upsert_game_result(res_data)
                        count += 1
            except Exception as e:
                print(f"[GRADING] Error fetching {league} {date_str}: {e}")
        # print(f"[GRADING] Updated {count} finals for {league}.")

    def _compute_clv_for_started_games(self):
        """
        Find predictions where game has started but close_line is NULL.
        Use OddsSelectionService to find the Closing Line (last snap <= start_time).
        """
        query = """
        SELECT m.id, m.event_id, m.market_type, m.pick, m.open_line, m.open_price, e.start_time
        FROM model_predictions m
        JOIN events e ON m.event_id = e.id
        WHERE m.close_line IS NULL 
          And datetime(e.start_time) < datetime('now') -- SQLite friendly
        """
        # Note: Postgres uses NOW()
        # For compatibility, let's select all NULL close_lines and filter in Python or use compatible syntax if possible
        # Or check DB type.
        
        query_candidates = """
        SELECT m.id, m.event_id, m.market_type, m.pick, m.open_line, m.open_price, e.start_time, e.league
        FROM model_predictions m
        JOIN events e ON m.event_id = e.id
        WHERE m.close_line IS NULL 
          AND e.start_time < CURRENT_TIMESTAMP -- Postgres
        """
        
        with get_db_connection() as conn:
            rows = _exec(conn, query_candidates).fetchall()
            
        updates = 0
        now = datetime.now() # naive or tz aware? DB timestamps usually naive UTC or similar in this app
        
        # print(f"[CLV] Checking {len(rows)} candidates for closing lines...")
        
        for r in rows:
            # Parse start_time
            st_raw = r['start_time']
            if not st_raw: continue
            
            # Simple check: has game started?
            # Assume DB stores ISO strings or datetime objects
            if isinstance(st_raw, str):
                try:
                    start_dt = datetime.fromisoformat(st_raw.replace('Z', '+00:00'))
                    # Strip TZ for naive comparison if needed, or ensure now is TZ aware
                    if start_dt.tzinfo:
                        start_dt = start_dt.replace(tzinfo=None) # naive UTC assumption
                except:
                    continue
            else:
                start_dt = st_raw # datetime object
            
            if start_dt > now:
                continue # Not started yet
                
            # Game Started: Find Closing Line
            # 1. Fetch all snapshots for event
            raw_snaps = []
            snap_q = "SELECT * FROM odds_snapshots WHERE event_id = :eid AND captured_at <= :st ORDER BY captured_at DESC LIMIT 100"
            
            # We need to format start_dt back to string for query if needed
            st_str = start_dt.isoformat()
            
            with get_db_connection() as conn:
                raw_snaps = [dict(s) for s in _exec(conn, snap_q, {"eid": r['event_id'], "st": st_str}).fetchall()]
                
            if not raw_snaps:
                # print(f"[CLV] No snapshots found before start for {r['event_id']}")
                continue
                
            # 2. Select 'Best' Closing Snapshot
            # Determine side from pick/market
            # Market type: SPREAD, TOTAL
            # Pick: Team Name (Spread) or OVER/UNDER (Total)
            
            # Map pick to side
            target_side = None
            if r['market_type'] == 'TOTAL':
                target_side = r['pick'] # OVER/UNDER
            elif r['market_type'] == 'SPREAD':
                # Pick is a Team Name. We need HOME/AWAY.
                # Use event or logic? 
                # Ideally selection service handles 'HOME'/'AWAY' if we pass it? 
                # Or we try to match pick to name?
                # Let's try both HOME/AWAY and see which matches pick?
                # Actually, simpler: Select Best SPREAD (priority). 
                # If that snapshot's home team == pick, side is HOME.
                pass
            
            # Use Selector
            best_snap = self.odds_selector.select_best_snapshot(raw_snaps, r['market_type'])
            
            if best_snap:
                close_line = best_snap.get('line_value')
                close_price = best_snap.get('price')
                
                if close_line is not None:
                    # Calculate CLV Points
                    # Spread: (Close - Open) * Direction
                    # If I extracted pick direction correctly...
                    
                    # Problem: r['pick'] is 'Duke'. best_snap has 'spread_home' (Duke by -5).
                    # We need to normalize.
                    
                    # If best_snap is flat row from DB: market_type, side, line_value...
                    # Oh, select_best_snapshot returns a SNAPSHOT ROW.
                    # It has 'side' (HOME/AWAY/OVER/UNDER).
                    pass
                    
                    # Logic:
                    # If I bet HOME -3. (Open = -3). 
                    # Closing Snap: HOME -5. (Close = -5).
                    # CLV = (-5) - (-3) = -2? 
                    # Wait. -5 is "Better" or "Worse"?
                    # Favored by 5 is "Better" than Favored by 3? 
                    # Actually, if I bet -3 (needing to win by >3), and market closes -5 (expects win by 5),
                    # I got a "good" number. -3 is EASIER to cover than -5.
                    # So CLV = Open - Close? (-3) - (-5) = +2 points. 
                    
                    # Example 2: Bet Under dog +7. Open = +7. 
                    # Closes +4. (Market lost faith in dog).
                    # I have +7. Market has +4.
                    # +7 is Better than +4.
                    # CLV = Open - Close = 7 - 4 = +3 points.
                    
                    # Does this hold? Open - Close works for standard conventions?
                    # Home -3 vs Home -5: -3 - (-5) = +2. Yes.
                    # Home +7 vs Home +4: 7 - 4 = +3. Yes.
                    
                    # Exception: TOTALS.
                    # Bet OVER 140. Closes 145.
                    # 140 is easier than 145. (Good).
                    # Open - Close = 140 - 145 = -5. (Bad sign?).
                    # For OVER, Lower is better. So Open < Close is GOOD.
                    # CLV = Close - Open? 145 - 140 = +5.
                    # Bet UNDER 140. Closes 135.
                    # 140 is easier than 135. (Good).
                    # Open > Close is GOOD.
                    # CLV = Open - Close? 140 - 135 = +5.
                    
                    # Formula:
                    # SPREAD: Open - Close (since line is relative to MY side... wait, DB lines are usually Home relative or Side relative?)
                    # model_predictions.bet_line IS relative to the pick in V2!
                    # So if I picked Duke -5, bet_line is -5.
                    
                    # We need the close_line RELATIVE TO THE PICK.
                    # best_snap has 'line_value' and 'side'.
                    # If best_snap['side'] == 'HOME' and pick is Home Team -> line matches.
                    # If best_snap['side'] == 'AWAY' and pick is Home Team -> line is inverted?
                    # The DB `odds_snapshots` usually stores line for the specific side.
                    # EXCEPT: Totals usually store the total score.
                    
                    # Let's trust `odds_selector` picked a relevant line.
                    # But `odds_selector` blindly picks "best" purely by priority. It might pick an AWAY line when I bet HOME line?
                    # Actually `odds_selector.select_best_snapshot` takes a `side` arg!
                    # I should pass the side I bet on!
                    
                    # Resolve side from pick
                    mapped_side = None
                    if r['market_type'] == 'TOTAL':
                        mapped_side = r['pick'] # OVER/UNDER
                    elif r['market_type'] == 'SPREAD':
                        q_ev = "SELECT home_team, away_team FROM events WHERE id=:eid"
                        with get_db_connection() as conn:
                            evt = _exec(conn, q_ev, {"eid": r['event_id']}).fetchone()
                            if evt:
                                if r['pick'] == evt['home_team']: mapped_side = 'HOME'
                                elif r['pick'] == evt['away_team']: mapped_side = 'AWAY'
                    
                    if mapped_side:
                        # Re-select with strict side
                        specific_snap = self.odds_selector.select_best_snapshot(raw_snaps, r['market_type'], side=mapped_side)
                        if specific_snap:
                            close_line = specific_snap['line_value']
                            close_price = specific_snap['price']
                            
                            # Final CLV calc
                            if r['market_type'] == 'SPREAD':
                                clv = r['open_line'] - close_line # Open - Close (since lower magnitude negative is good/bad??)
                                # Let's re-verify:
                                # Bet Home -3. Close Home -5.
                                # -3 - (-5) = +2. Good.
                                # Bet Home +7. Close Home +4.
                                # +7 - 4 = +3. Good.
                                # Bet Home +3. Close Home +5.
                                # +3 - 5 = -2. Bad.
                                # Seems correct: Open - Close.
                                
                            elif r['market_type'] == 'TOTAL':
                                if r['pick'] == 'OVER':
                                    clv = close_line - r['open_line'] # Close - Open
                                else:
                                    clv = r['open_line'] - close_line # Open - Close
                            else:
                                clv = 0 # ML todo
                                
                            # Update DB
                            u_q = """
                            UPDATE model_predictions SET 
                                close_line=:cl, close_price=:cp, clv_points=:cv, close_captured_at=:ts
                            WHERE id=:id
                            """
                            with get_db_connection() as conn:
                                _exec(conn, u_q, {
                                    "cl": close_line,
                                    "cp": close_price,
                                    "cv": clv,
                                    "ts": specific_snap['captured_at'],
                                    "id": r['id']
                                })
                                conn.commit()
                            updates += 1
                            
        return updates

    def _evaluate_db_predictions(self):
        """
        Query DB for pending predictions where the game is FINAL.
        """
        # Join model_predictions -> events -> game_results
        query = """
        SELECT m.id, m.market_type, m.pick, m.bet_line, m.book,
               e.home_team, e.away_team,
               gr.home_score, gr.away_score, gr.final
        FROM model_predictions m
        JOIN events e ON m.event_id = e.id
        JOIN game_results gr ON e.id = gr.event_id
        WHERE (m.outcome = 'PENDING' OR m.outcome IS NULL)
          AND gr.final = TRUE
        """
        
        with get_db_connection() as conn:
            rows = _exec(conn, query).fetchall()
            
        print(f"[GRADING] Found {len(rows)} pending bets with final scores.")
        
        graded = 0
        for row in rows:
            try:
                outcome = self._grade_row(dict(row))
                if outcome != 'PENDING':
                    update_model_prediction_result(row['id'], outcome)
                    graded += 1
            except Exception as e:
                print(f"[GRADING] Error grading row {row['id']}: {e}")
                
        return graded

    def _grade_row(self, row):
        market = row['market_type'] # SPREAD, TOTAL, ML
        pick = row['pick']
        line = float(row['bet_line']) if row['bet_line'] is not None else 0.0
        
        h_score = row['home_score']
        a_score = row['away_score']
        
        outcome = 'PENDING'
        
        if market == 'SPREAD':
            if pick == row['home_team']:
                score = h_score
                opp_score = a_score
            elif pick == row['away_team']:
                score = a_score
                opp_score = h_score
            else:
                return 'VOID'
            
            if score + line > opp_score: outcome = 'WON'
            elif score + line < opp_score: outcome = 'LOST'
            else: outcome = 'PUSH'
            
        elif market == 'TOTAL':
            total_score = h_score + a_score
            if pick.upper() == 'OVER':
                outcome = 'WON' if total_score > line else 'LOST' if total_score < line else 'PUSH'
            elif pick.upper() == 'UNDER':
                outcome = 'WON' if total_score < line else 'LOST' if total_score > line else 'PUSH'
                
        elif market == 'ML' or market == 'MONEYLINE':
            winner = row['home_team'] if h_score > a_score else row['away_team']
            if pick == winner: outcome = 'WON'
            else: outcome = 'LOST'
            
        return outcome

if __name__ == "__main__":
    service = GradingService()
    res = service.grade_predictions()
    print(res)
