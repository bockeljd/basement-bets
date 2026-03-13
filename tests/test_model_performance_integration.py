
import pytest
from fastapi.testclient import TestClient
from src.api import app
from src.database import get_db_connection, _exec
from src.config import settings
import uuid
import os
from datetime import datetime, timedelta

client = TestClient(app)

def check_test_db_safety():
    """Strict safety gate: fail-fast unless TESTING=true and DB is local/test."""
    testing_env = os.environ.get("TESTING", "").lower() == "true"
    dsn = (settings.DATABASE_URL or "").lower()
    
    # Must have explicit TESTING signal
    if not testing_env:
        pytest.exit("SAFETY ERROR: TESTING=true environment variable not set. Aborting DB-writing tests.")
    
    # Must be pointed at test/staging/local DB
    is_safe_db = any(k in dsn for k in ['test', 'staging', 'localhost', '127.0.0.1'])
    
    # Hard block on production identifiers
    is_prod = any(k in dsn for k in ['prod', 'production', 'main']) or settings.APP_ENV in ['prod', 'production']
    
    if is_prod or not is_safe_db:
        pytest.exit(f"SAFETY ERROR: Tests attempted to run against a potentially PRODUCTION database: {dsn}. Aborting.")

class DBFixture:
    def __init__(self):
        check_test_db_safety()
        self.slate_ids = []
        self.event_ids = []
        self.prediction_ids = []

    def cleanup(self):
        """Cleanup seeded data in strict FK order (children before parents)."""
        with get_db_connection() as conn:
            # 1. Child rows (recommended_slate_items)
            if self.prediction_ids:
                _exec(conn, "DELETE FROM recommended_slate_items WHERE prediction_id IN %s", (tuple(self.prediction_ids),))
            
            # 2. Parent rows
            if self.prediction_ids:
                _exec(conn, "DELETE FROM model_predictions WHERE id IN %s", (tuple(self.prediction_ids),))
            if self.slate_ids:
                _exec(conn, "DELETE FROM recommended_slates WHERE id IN %s", (tuple(self.slate_ids),))
            if self.event_ids:
                _exec(conn, "DELETE FROM events WHERE id IN %s", (tuple(self.event_ids),))
            
            conn.commit()

@pytest.fixture
def db_fix():
    fix = DBFixture()
    yield fix
    fix.cleanup()

def test_history_prioritization_and_metadata(db_fix):
    """Verify prioritization of canonical slate and source_type metadata."""
    date_et = "2026-03-10"
    unique_suffix = uuid.uuid4().hex[:8]
    league = f"TEST_NBA_{unique_suffix}"
    slate_id = f"can_slate_{unique_suffix}"
    event_id = f"can_evt_{unique_suffix}"
    pred_id = f"can_pred_{unique_suffix}"
    
    db_fix.slate_ids.append(slate_id)
    db_fix.event_ids.append(event_id)
    db_fix.prediction_ids.append(pred_id)
    
    with get_db_connection() as conn:
        _exec(conn, "INSERT INTO recommended_slates (id, league, date_et, source) VALUES (%s, %s, %s, 'full')", (slate_id, league, date_et))
        _exec(conn, "INSERT INTO events (id, league, start_time, home_team, away_team, status) VALUES (%s, %s, '2026-03-10 20:00:00+00', 'Team A', 'Team B', 'FINAL')", (event_id, league))
        _exec(conn, "INSERT INTO model_predictions (id, event_id, market_type, outcome, confidence_0_100, ev_per_unit, analyzed_at) VALUES (%s, %s, 'h2h', 'WON', 85, 0.05, NOW())", (pred_id, event_id))
        _exec(conn, "INSERT INTO recommended_slate_items (slate_id, prediction_id, event_id, rank, market_type) VALUES (%s, %s, %s, 1, 'h2h')", (slate_id, pred_id, event_id))
        conn.commit()
    
    response = client.get(f"/api/research/history?lookback_days=400&limit=100", headers={"X-BASEMENT-KEY": "Xavier"})
    assert response.status_code == 200
    data = response.json()
    
    target = next((r for r in data if r.get('prediction_id') == pred_id or r.get('id') == pred_id), None)
    assert target is not None, f"Seeded canonical prediction {pred_id} not found"
    assert target.get('source_type') == 'canonical_slate'
    assert 'day_et' in target
    assert 'rank' in target
    assert target['day_et'] == date_et

def test_history_fallback_behavior(db_fix):
    """Verify the fallback path picking up non-canonical rows deterministically."""
    from src.database import fetch_model_history
    unique_suffix = uuid.uuid4().hex[:8]
    league = f"TEST_FALLBACK_{unique_suffix}"
    event_id = f"fall_evt_{unique_suffix}"
    pred_id = f"fall_pred_{unique_suffix}"
    
    past_st = (datetime.now() - timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S+00')
    
    db_fix.event_ids.append(event_id)
    db_fix.prediction_ids.append(pred_id)
    
    with get_db_connection() as conn:
        _exec(conn, """
            INSERT INTO events (id, league, start_time, home_team, away_team, status)
            VALUES (%s, %s, %s, 'Fall A', 'Fall B', 'FINAL')
        """, (event_id, league, past_st))
        
        _exec(conn, """
            INSERT INTO model_predictions (id, event_id, market_type, outcome, analyzed_at, ev_per_unit, pick, selection)
            VALUES (%s, %s, 'h2h', 'WON', NOW(), 0.05, 'AWAY', 'Away Team')
        """, (pred_id, event_id))
        conn.commit()
    
    # DETERMINISTIC PROOF: Test the fallback query function directly
    # This must find our seeded row without interference from canonical slates.
    rows = fetch_model_history(user_id=None, recommended_only=True, limit=50, lookback_days=10)
    target = next((r for r in rows if r.get('id') == pred_id), None)
    
    assert target is not None, f"Deterministic fallback proof failed: seeded row {pred_id} not returned by query."
    assert target.get('event_id') == event_id

def test_ncaam_rank_6_inclusion(db_fix):
    """Verify NCAAM model-performance series includes rank 6 by asserting a delta in counts."""
    unique_suffix = uuid.uuid4().hex[:8]
    slate_id = f"r6_slate_{unique_suffix}"
    event_id = f"r6_evt_{unique_suffix}"
    pred_id = f"r6_pred_{unique_suffix}"
    
    # Isolated day within 180-day series lookback
    isolated_date = (datetime.now() - timedelta(days=90))
    day = isolated_date.strftime('%Y-%m-%d')
    start_time_str = isolated_date.strftime('%Y-%m-%d 20:00:00+00')
    
    # 1. Get baseline count for this day
    def get_count_for_day(d_str):
        resp = client.get(f"/api/ncaam/model-performance/series?days=150&min_ev=0.01", headers={"X-BASEMENT-KEY": "Xavier"})
        if resp.status_code != 200: return 0
        s_data = resp.json().get('series', [])
        d_stat = next((s for s in s_data if s.get('day') == d_str), None)
        return d_stat['n'] if d_stat else 0

    baseline_n = get_count_for_day(day)
    
    # 2. Seed rank-6 data
    db_fix.slate_ids.append(slate_id)
    db_fix.event_ids.append(event_id)
    db_fix.prediction_ids.append(pred_id)
    
    with get_db_connection() as conn:
        _exec(conn, "INSERT INTO recommended_slates (id, league, date_et, source) VALUES (%s, 'NCAAM', %s, 'full')", (slate_id, day))
        _exec(conn, "INSERT INTO events (id, league, start_time, home_team, away_team, status) VALUES (%s, 'NCAAM', %s, 'R6 A', 'R6 B', 'FINAL')", (event_id, start_time_str))
        _exec(conn, """
            INSERT INTO model_predictions (id, event_id, market_type, outcome, analyzed_at, bet_price, confidence_0_100, ev_per_unit) 
            VALUES (%s, %s, 'h2h', 'WON', %s, -110, 85, 0.05)
        """, (pred_id, event_id, start_time_str))
        _exec(conn, "INSERT INTO recommended_slate_items (slate_id, prediction_id, event_id, rank) VALUES (%s, %s, %s, 6)", (slate_id, pred_id, event_id))
        conn.commit()
    
    # 3. Assert delta = 1
    new_n = get_count_for_day(day)
    assert new_n == baseline_n + 1, f"DETERMINISTIC PROOF FAILED: Count did not increase by 1 for rank-6 seed. (Before: {baseline_n}, After: {new_n})"
