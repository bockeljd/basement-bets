
import sys
import os
import uuid
import random
from datetime import datetime, timedelta

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from src.database import get_db_connection, _exec, insert_model_prediction

def seed_performance_data():
    print("Seeding graded predictions for Summary Tab validation...")
    
    # 20 Wins (Spread)
    # 15 Losses (Spread)
    # 5 Pushes
    
    start_date = datetime.now() - timedelta(days=30)
    
    with get_db_connection() as conn:
        # Create a mock league event if needed to link FK
        # Usually we link to existing events, but for speed we might need generic ones.
        # However, FK constraint exists. We must use existing event_ids or create them.
        # Let's create one mock past event per prediction? Overkill.
        # Let's create one mock event and link multiple predictions to it?
        # Or better, fetch existing event IDs from DB.
        
        event_ids = [r['id'] for r in _exec(conn, "SELECT id FROM events LIMIT 50").fetchall()]
        
        if not event_ids:
            # Create a fallback event
            eid = f"seed_event_{uuid.uuid4().hex[:8]}"
            _exec(conn, """
                INSERT INTO events (id, league, home_team, away_team, start_time, status)
                VALUES (:id, 'NCAAM', 'Seed Home', 'Seed Away', NOW() - INTERVAL '2 days', 'FINAL')
                ON CONFLICT (id) DO NOTHING
            """, {"id": eid})
            event_ids = [eid]
            conn.commit()
            
    total_seeded = 0
    
    for i in range(40):
        outcome = "WON" if i < 20 else "LOST" if i < 35 else "PUSH"
        if outcome == "WON":
            edge = random.uniform(2.0, 5.0)
            clv = random.uniform(0.5, 2.0)
        elif outcome == "LOST":
            edge = random.uniform(0.5, 3.0)
            clv = random.uniform(-1.0, 1.0)
        else:
            edge = 1.0
            clv = 0.0
            
        pred = {
            "event_id": random.choice(event_ids),
            "analyzed_at": (start_date + timedelta(days=i)).isoformat(),
            "model_version": "2.0.0-seed",
            "market_type": "SPREAD",
            "pick": "HOME",
            "bet_line": -3.5,
            "bet_price": -110,
            "book": "SeedBook",
            "mu_market": 4.0,
            "mu_torvik": 6.0,
            "mu_final": 5.0,
            "sigma": 10.0,
            "win_prob": 0.55,
            "ev_per_unit": edge * 1.5, # Rough proxy
            "confidence_0_100": int(edge * 20),
            "inputs_json": "{}",
            "outputs_json": "{}",
            "narrative_json": "{}",
            "close_captured_at": None,
            "outcome": outcome,
            "edge_points": edge,
            "clv_points": clv,
            "selection": "HOME"
        }
        insert_model_prediction(pred)
        total_seeded += 1
        
    print(f"Seeded {total_seeded} graded predictions.")

if __name__ == "__main__":
    seed_performance_data()
