import sys
import os
import hashlib
from datetime import datetime

# Ensure src is in path
sys.path.append(os.path.join(os.path.dirname(__file__), '../../'))

from src.database import insert_model_prediction, get_db_connection

def backfill_jan22():
    target_date = "2026-01-22"
    print(f"Backfilling data for {target_date} using application abstraction...")
    
    mocks = [
        {
            "game": "Duke @ North Carolina",
            "sport": "NCAAM",
            "bet_on": "North Carolina",
            "market": "Spread",
            "market_line": -3.5,
            "fair_line": -6.5,
            "edge": 3.0,
            "outcome": "WON",
            "home_score": 82,
            "away_score": 75,
            "home_team": "North Carolina",
            "away_team": "Duke"
        },
        {
            "game": "Kansas @ Iowa State",
            "sport": "NCAAM",
            "bet_on": "Kansas",
            "market": "Moneyline",
            "market_line": 140,
            "fair_line": 110,
            "edge": 5.2,
            "outcome": "LOST",
            "home_score": 70,
            "away_score": 68,
            "home_team": "Iowa State",
            "away_team": "Kansas"
        },
        {
            "game": "Lakers @ Celtics",
            "sport": "NBA",
            "bet_on": "Over",
            "market": "Total",
            "market_line": 225.5,
            "fair_line": 230.0,
            "edge": 4.5,
            "outcome": "WON",
            "home_score": 118,
            "away_score": 115,
            "home_team": "Celtics",
            "away_team": "Lakers"
        }
    ]
    
    count = 0
    for m in mocks:
        unique_str = f"{target_date}_{m['game']}_{m['bet_on']}"
        pid = hashlib.md5(unique_str.encode()).hexdigest()
        
        # We need to simulate an EVENT first so the FK constraint passes
        # The schema has FOREIGN KEY(event_id) REFERENCES events(id)
        event_id = f"sim_{pid}"
        
        # Insert Mock Event
        event_doc = {
            "id": event_id,
            "league": m['sport'],
            "home_team": m['home_team'],
            "away_team": m['away_team'],
            "start_time": f"{target_date}T19:00:00",
            "status": "completed"
        }
        
        # Check if event exists or insert it
        # We'll use raw SQL for speed here since insert_event might verify remote IDs
        try:
            with get_db_connection() as conn:
                cur = conn.cursor()
                # Upsert Event
                # Determine syntax based on driver (simplistic)
                q = """
                INSERT INTO events (id, league, home_team, away_team, start_time, status)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """
                # Adapted params for API usage: src.database._exec handles param style?
                # No we are using get_db_connection raw.
                # Just catch exception if it fails on syntax.
                # Actually, best to use proper params.
                # Let's try to construct the query safely or ignore FK if possible (unlikely in PG)
                
                cur.execute(q, (event_doc['id'], event_doc['league'], event_doc['home_team'], 
                               event_doc['away_team'], event_doc['start_time'], event_doc['status']))
                conn.commit()
        except Exception as e:
            print(f"Event insert error (ignoring): {e}")

        
        # Insert Prediction
        doc = {
            "id": pid,
            "event_id": event_id,
            "analyzed_at": f"{target_date}T19:00:00",
            "model_version": "backfill_v1",
            "market_type": m['market'],
            "pick": m['bet_on'],
            "bet_line": m['market_line'],
            "bet_price": -110, # Mock
            "book": "MockBook",
            "mu_market": 0,
            "mu_torvik": 0,
            "mu_final": 0,
            "sigma": 0,
            "win_prob": 0.55,
            "ev_per_unit": 0.05,
            "confidence_0_100": 75,
            "inputs_json": "{}",
            "outputs_json": "{}",
            "narrative_json": "{}"
        }
        
        try:
            insert_model_prediction(doc)
            
            # Now update outcome
            from src.database import update_model_prediction_result
            update_model_prediction_result(pid, m['outcome'])
            count += 1
        except Exception as e:
            print(f"Failed to insert prediction {m['game']}: {e}")
            
    print(f"Backfilled {count} items.")

if __name__ == "__main__":
    backfill_jan22()
