import pandas as pd
import sys
import os
from datetime import datetime, timedelta

# Path Setup
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from src.database import get_db_connection
from src.services.auditor import ResearchAuditor

class BacktestEngine:
    def __init__(self):
        self.auditor = ResearchAuditor()
        
    def fetch_historical_games(self, sport, days=30):
        """
        Fetch completed games with scores from DB.
        """
        table = 'games'
        query = f"""
            SELECT * FROM {table} 
            WHERE sport_key LIKE ? 
            AND status = 'completed'
            AND commence_time > date('now', '-{days} days')
        """
        # Map sport to key pattern
        key_pattern = '%'
        if sport == 'NCAAM': key_pattern = '%ncaab%'
        elif sport == 'NFL': key_pattern = '%nfl%'
        elif sport == 'EPL': key_pattern = '%epl%'
        
        with get_db_connection() as conn:
            # Handle SQLite differences
            if 'sqlite' in str(conn):
                 cur = conn.cursor()
                 cur.execute(query, (key_pattern,))
                 rows = cur.fetchall()
                 return [dict(r) for r in rows]
            else:
                 # Postgres
                 with conn.cursor() as cur:
                     cur.execute(query.replace('?', '%s'), (key_pattern,))
                     rows = cur.fetchall()
                     return [dict(r) for r in rows]

    def run_backtest(self, sport, days=30):
        """
        Replay models on historical games.
        Note: True backtesting requires historical ODDS which we might lack.
        We will simulate using 'Closing Odds' if in DB, or skip.
        """
        print(f"--- Backtesting {sport} (Last {days} Days) ---")
        games = self.fetch_historical_games(sport, days)
        print(f"Found {len(games)} historical games to test.")
        
        results = []
        
        # Load Model
        model = None
        if sport == 'NCAAM':
            from src.models.ncaam_model import NCAAMModel
            model = NCAAMModel()
        elif sport == 'NFL':
            from src.models.nfl_model import NFLModel
            model = NFLModel()
        
        if not model:
            print("Model not supported for backtest.")
            return

        for game in games:
            # Simulate "Prediction"
            # We need the inputs the model uses. 
            # NCAAM uses BartTorvik stats (time invariant-ish for effective validation).
            # NFL uses recent data.
            
            # 1. Run Prediction
            # We need to construct a 'game' object similar to what find_edges receives
            # But wait, find_edges calls API. We want to bypass API and use DB game data.
            
            home = game['home_team']
            away = game['away_team']
            
            # Mock Odds (Use a standard line or extract from game if stored?)
            # DB 'games' table doesn't have odds usually unless we enhanced it.
            # Assuming we can't get true Closing Odds easily without a history table.
            # Let's check 'model_predictions' table instead!
            # The user wants to validate "Predictions made".
            
            pass 

    def analyze_predictions(self):
        """
        Analyze existing 'model_predictions' against outcomes.
        This is "Forward Testing" validation rather than "Backtesting".
        """
        print("\n--- Validating Past Predictions ---")
        query = """
            SELECT * FROM model_predictions 
            WHERE result IN ('Win', 'Loss', 'Push')
        """
        with get_db_connection() as conn:
             cur = conn.cursor()
             cur.execute(query)
             rows = cur.fetchall()
             preds = [dict(r) for r in rows]
             
        if not preds:
            print("No graded predictions found to analyze.")
            return
            
        df = pd.DataFrame(preds)
        print(f"analyzing {len(df)} graded bets.")
        
        # Win Rate
        wins = df[df['result'] == 'Win'].shape[0]
        total = df.shape[0]
        wr = (wins / total * 100)
        
        # ROI (assuming flat unit)
        units_won = wins * 0.909 - (total - wins) * 1.0 # @ -110
        roi = units_won / total * 100
        
        print(f"Win Rate: {wr:.1f}%")
        print(f"Est ROI: {roi:.1f}%")
        
        # Breakdown by Sport
        print("\nBy Sport:")
        print(df.groupby('sport')['result'].value_counts(normalize=True))

if __name__ == "__main__":
    engine = BacktestEngine()
    engine.analyze_predictions()
