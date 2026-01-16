
import unittest
import sqlite3
import datetime
from unittest.mock import patch
from src.services.evaluation_service import EvaluationService

# Mock DB Schema
SCHEMA = """
CREATE TABLE IF NOT EXISTS events_v2 (
    id TEXT PRIMARY KEY,
    start_time TIMESTAMP
);
CREATE TABLE IF NOT EXISTS model_versions (
    id INTEGER PRIMARY KEY,
    sport TEXT,
    version_tag TEXT
);
CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY,
    model_version_id INTEGER,
    event_id TEXT,
    league TEXT,
    market_type TEXT,
    output_win_prob REAL,
    output_implied_margin REAL,
    output_implied_total REAL
);
CREATE TABLE IF NOT EXISTS settlement_events (
    fingerprint TEXT PRIMARY KEY,
    event_id TEXT,
    outcome TEXT,
    result TEXT,
    computed TEXT
);
CREATE TABLE IF NOT EXISTS model_health_daily (
    date DATE NOT NULL,
    model_version_id INTEGER NOT NULL,
    league TEXT,
    market_type TEXT,
    metric_name TEXT NOT NULL,
    metric_value REAL,
    sample_size INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(date, model_version_id, league, market_type, metric_name)
);
"""

class TestModelEvaluation(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        
    def tearDown(self):
        self.conn.close()
        
    @patch('src.services.evaluation_service.get_db_connection')
    @patch('src.database.get_db_connection')
    def test_daily_evaluation(self, mock_db_conn1, mock_db_conn2):
        # Setup Mocks to return our in-memory conn
        # Context manager support
        mock_db_conn1.return_value.__enter__.return_value = self.conn
        mock_db_conn1.return_value.__exit__.return_value = None
        mock_db_conn2.return_value.__enter__.return_value = self.conn
        mock_db_conn2.return_value.__exit__.return_value = None
        
        # 1. Seed Data
        today = datetime.date.today()
        eid = "event-123"
        
        # Event
        self.conn.execute("INSERT INTO events_v2 (id, start_time) VALUES (?, ?)", (eid, today.isoformat()))
        
        # Model
        self.conn.execute("INSERT INTO model_versions (id, sport, version_tag) VALUES (1, 'NFL', 'v1')")
        
        # Prediction (High Confidence Win)
        self.conn.execute("""
            INSERT INTO predictions (model_version_id, event_id, league, market_type, output_win_prob) 
            VALUES (1, ?, 'NFL', 'Moneyline', 0.8)
        """, (eid,))
        
        # Settlement (WON)
        self.conn.execute("""
            INSERT INTO settlement_events (fingerprint, event_id, outcome, result, computed)
            VALUES ('fp1', ?, 'WON', '{}', '{}')
        """, (eid,))
        
        self.conn.commit()
        
        # 2. Run Evaluation
        svc = EvaluationService()
        count = svc.evaluate_daily_performance(target_date=today)
        
        self.assertEqual(count, 3) # Brier, LogLoss, Accuracy
        
        # 3. Verify Metrics
        cur = self.conn.execute("SELECT metric_name, metric_value FROM model_health_daily")
        rows = {r['metric_name']: r['metric_value'] for r in cur.fetchall()}
        
        # Prob = 0.8, Actual = 1.0
        # Brier = (0.8 - 1.0)^2 = (-0.2)^2 = 0.04
        self.assertAlmostEqual(rows['brier_score'], 0.04)
        
        # Accuracy = 1.0 (Correct)
        self.assertEqual(rows['accuracy'], 1.0)
        
        # LogLoss = -log(0.8) ~= 0.223
        self.assertAlmostEqual(rows['log_loss'], 0.2231, places=3)
        
if __name__ == '__main__':
    unittest.main()
