import pandas as pd
import sys
import os
from datetime import datetime, timedelta

# Path Setup
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from src.database import get_db_connection, _exec
from src.services.auditor import ResearchAuditor

class BacktestEngine:
    def __init__(self):
        self.auditor = ResearchAuditor()
        
    def fetch_historical_games(self, sport, days=30):
        """
        Fetch completed games with scores from DB (Postgres).
        """
        # Legacy 'games' table is gone. Use events + game_results.
        query = """
            SELECT e.*, gr.home_score, gr.away_score 
            FROM events e
            JOIN game_results gr ON e.id = gr.event_id
            WHERE e.sport_key LIKE :key_pattern 
            AND e.status IN ('completed', 'closed', 'final')
            AND e.start_time > CURRENT_DATE - INTERVAL :interval
        """
        # Map sport to key pattern
        key_pattern = '%'
        if sport == 'NCAAM': key_pattern = '%ncaab%' # OddsAPI key convention
        elif sport == 'NFL': key_pattern = '%nfl%'
        elif sport == 'EPL': key_pattern = '%epl%'
        
        interval = f"{days} days"
        
        with get_db_connection() as conn:
             cursor = _exec(conn, query, {"key_pattern": key_pattern, "interval": days}) # Wait, param substitution for INTERVAL? 
             # Postgres INTERVAL :days || ' days'? Or pass string.
             # _exec converts :key.
             # Easier: Parametrize the interval construction in SQL or pass fully formed interval string?
             
             # Let's rebuild query to use python formatting for interval string (safe enough if int) or proper date math.
             # e.start_time > NOW() - make_interval(days := :days)
             
             q2 = """
                SELECT e.*, gr.home_score, gr.away_score 
                FROM events e
                JOIN game_results gr ON e.id = gr.event_id
                WHERE e.sport_key LIKE :key_pattern 
                AND (e.status = 'completed' OR e.status = 'final')
                AND e.start_time > NOW() - (:days || ' days')::INTERVAL
             """
             rows = _exec(conn, q2, {"key_pattern": key_pattern, "days": days}).fetchall()
             return [dict(r) for r in rows]

    def run_backtest(self, sport, days=30):
        """
        Replay models on historical games.
        """
        print(f"--- Backtesting {sport} (Last {days} Days) ---")
        games = self.fetch_historical_games(sport, days)
        print(f"Found {len(games)} historical games to test.")
        
        # Stub for model logic...
        pass 

    def analyze_predictions(self):
        """
        Analyze existing 'model_predictions' against outcomes.
        """
        print("\n--- Validating Past Predictions ---")
        # 'result' column removed/renamed to 'outcome'.
        query = """
            SELECT m.*, e.league as sport 
            FROM model_predictions m
            JOIN events e ON m.event_id = e.id
            WHERE outcome IN ('WON', 'LOST', 'PUSH', 'Win', 'Loss', 'Push')
        """
        with get_db_connection() as conn:
             cursor = _exec(conn, query)
             rows = cursor.fetchall()
             preds = [dict(r) for r in rows]
             
        if not preds:
            print("No graded predictions found to analyze.")
            return
            
        df = pd.DataFrame(preds)
        print(f"Analyzing {len(df)} graded bets.")
        
        # Normalize Outcome
        df['outcome'] = df['outcome'].str.upper().replace({'WIN': 'WON', 'LOSS': 'LOST'})
        
        # Win Rate
        wins = df[df['outcome'] == 'WON'].shape[0]
        total = df.shape[0]
        wr = (wins / total * 100)
        
        # ROI (naive)
        units_won = wins * 0.909 - (total - wins) * 1.0 # @ -110
        roi = units_won / total * 100
        
        print(f"Win Rate: {wr:.1f}%")
        print(f"Est ROI: {roi:.1f}%")
        
        if 'sport' in df.columns:
            print("\nBy Sport:")
            print(df.groupby('sport')['outcome'].value_counts(normalize=True))

if __name__ == "__main__":
    engine = BacktestEngine()
    engine.analyze_predictions()
