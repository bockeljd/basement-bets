
import pytest
from fastapi.testclient import TestClient
from src.api import app
from src.database import get_db_connection, _exec
from src.services.evaluation_service import EvaluationService
from datetime import date
import json

client = TestClient(app)

def setup_seeded_data():
    """
    Seed:
    - 1 Bet: $100 on Home Team (-110 / 1.91), Result: WON.
    - 1 Prediction: Win Prob 0.60.
    - 1 Settlement: inputs incl CLV (-110).
    """
    txn_date = date.today().strftime("%Y-%m-%d")
    
    with get_db_connection() as conn:
        # Clean
        _exec(conn, "DELETE FROM model_health_daily WHERE date = :d", {"d": txn_date})
        # Insert event
        _exec(conn, "INSERT OR IGNORE INTO events (id, league, start_time, home_team_id, away_team_id, home_team, away_team, status) VALUES ('evt_seed_99', 'NFL', '2025-01-01 20:00:00', 'team_A', 'team_B', 'Team A', 'Team B', 'SCHEDULED')")
        
        import uuid
        test_uid = str(uuid.uuid4())
        # Insert bet + leg
        _exec(conn, "INSERT OR IGNORE INTO bets (id, user_id, provider, date, sport, bet_type, wager, profit, status, raw_text, hash_id, description, selection) VALUES (999, :uid, 'DK', :d, 'NFL', 'Moneyline', 100.0, 91.0, 'WON', 'Seed', 'hash999', 'Team A vs Team B', 'Team A')", {"d": txn_date, "uid": test_uid})
        
        _exec(conn, "INSERT OR IGNORE INTO bet_legs (id, bet_id, leg_type, market_key, selection, odds_american, status, event_id) VALUES (99901, 999, 'Moneyline', 'Moneyline', 'Team A', -110, 'WON', 'evt_seed_99')")
        
        # Insert Prediction
        _exec(conn, "INSERT OR IGNORE INTO predictions (model_version_id, event_id, league, market_type, output_win_prob) VALUES (1, 'evt_seed_99', 'NFL', 'Moneyline', 0.60)")
        
        # Insert Settlement
        inputs = json.dumps({
            "clv": {"line": -115, "price": -115, "book": "consensus"},
            "line": -110,
            "odds_american": -110
        })
        _exec(conn, "INSERT OR IGNORE INTO settlement_events (id, event_id, leg_id, outcome, inputs_json) VALUES (1, 'evt_seed_99', 99901, 'WON', :j)", {"j": inputs})
        
        conn.commit()

def test_evaluation_api():
    # 1. Setup
    setup_seeded_data()
    
    # 2. Run Evaluation
    svc = EvaluationService()
    count = svc.evaluate_daily_performance(date.today())
    assert count > 0
    
    # 3. Call API
    response = client.get("/api/model-health/daily")
    assert response.status_code == 200
    data = response.json()
    
    assert len(data) > 0
    
    # Verify Metrics for today
    today_str = date.today().strftime("%Y-%m-%d")
    daily_rows = [r for r in data if r['date'] == today_str and r['model_version_id'] == 'test_model_v1']
    
    print(f"DEBUG API Data: {daily_rows}")
    
    roi_row = next((r for r in daily_rows if r['metric_name'] == 'roi'), None)
    assert roi_row is not None
    # Profit 91 / Wager 100 = 0.91
    assert abs(roi_row['metric_value'] - 0.91) < 0.01

    brier_row = next((r for r in daily_rows if r['metric_name'] == 'brier_score'), None)
    assert brier_row is not None
    # Prob 0.60, Actual 1.0. (0.6 - 1.0)^2 = 0.16
    assert abs(brier_row['metric_value'] - 0.16) < 0.01

if __name__ == "__main__":
    test_evaluation_api()
