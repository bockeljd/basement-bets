
import unittest
import sqlite3
import uuid
import json
from src.services.settlement_service import SettlementEngine
from src.database import init_db, init_ingestion_backbone_db, init_game_results_db, init_props_parlays_db, init_settlement_db

class TestSettlementHardening(unittest.TestCase):
    def setUp(self):
        # In-memory DB for isolation
        self.conn = sqlite3.connect(":memory:")
        # Enable FKs
        self.conn.execute("PRAGMA foreign_keys = ON;")
        
        # Init Schemas (Manually or via init functions adapted for conn)
        # Since init functions usually take a path or check env, we might need to mock get_db_connection
        # Or just recreate schema manually here for speed/control.
        
        self.conn.executescript("""
        CREATE TABLE events_v2 (
            id TEXT PRIMARY KEY,
            league TEXT,
            home_team_id TEXT,
            away_team_id TEXT,
            start_time TIMESTAMP,
            status TEXT DEFAULT 'scheduled'
        );
        CREATE TABLE event_providers (
            event_id TEXT,
            provider TEXT,
            provider_event_id TEXT,
            PRIMARY KEY(provider, provider_event_id)
        );
        CREATE TABLE game_results (
            event_id TEXT PRIMARY KEY,
            home_score INTEGER,
            away_score INTEGER,
            final BOOLEAN DEFAULT 0,
            status TEXT,
            source_provider TEXT, -- Added
            final_at TIMESTAMP, -- Added
            period TEXT, -- Parsing Requirement
            updated_at TIMESTAMP -- Added
        );
        CREATE TABLE bets (
            id INTEGER PRIMARY KEY,
            provider TEXT,
            status TEXT DEFAULT 'PENDING'
        );
        CREATE TABLE bet_legs (
            id INTEGER PRIMARY KEY,
            bet_id INTEGER,
            event_id TEXT,
            leg_type TEXT, -- market_type
            selection TEXT,
            side TEXT,
            line_value REAL,
            status TEXT DEFAULT 'PENDING',
            selection_team_id TEXT,
            FOREIGN KEY(bet_id) REFERENCES bets(id)
        );
        CREATE TABLE settlement_events (
            id TEXT PRIMARY KEY,
            bet_id INTEGER NOT NULL,
            leg_id INTEGER NOT NULL,
            event_id TEXT NOT NULL,
            outcome TEXT NOT NULL,
            graded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            graded_by TEXT DEFAULT 'system',
            grading_version TEXT DEFAULT 'v1',
            fingerprint TEXT NOT NULL UNIQUE,
            inputs_json TEXT,
            result_revision INTEGER DEFAULT 0
        );
        """)
        
        # Patch SettlementEngine to use our conn
        self.engine = SettlementEngine()
        # We need to mock get_db_connection to return self.conn
        # Or modify engine methods to accept conn. (They do! run() creates one, but separate methods take one)
        # But run() calls get_db_connection.
        
    def tearDown(self):
        self.conn.close()

    def test_idempotency(self):
        # 1. Setup Data
        eid = str(uuid.uuid4())
        self.conn.execute("INSERT INTO events_v2 (id, league) VALUES (?, ?)", (eid, "NCAAM"))
        self.conn.execute("INSERT INTO game_results (event_id, home_score, away_score, final) VALUES (?, 80, 70, 1)", (eid,))
        self.conn.execute("INSERT INTO bets (id, provider) VALUES (1, 'DK')")
        self.conn.execute("""
            INSERT INTO bet_legs (id, bet_id, event_id, leg_type, side, status) 
            VALUES (101, 1, ?, 'MONEYLINE', 'HOME', 'PENDING')
        """, (eid,))
        self.conn.commit()

        # 2. Run Grade (Manually calling private methods to inject conn)
        legs = self.engine._fetch_candidate_legs(self.conn, league=None, limit=100)
        self.assertEqual(len(legs), 1)
        
        result = self.engine._fetch_final_result(self.conn, eid)
        outcome, _, _ = self.engine._grade_leg(legs[0], result)
        self.assertEqual(outcome, "WON")
        
        # 3. Insert Settlement - First Time
        # Need to construct inputs manually as per run()
        fp_parts = [eid, "80", "70", "MONEYLINE", "HOME", "", self.engine.GRADING_VERSION]
        from src.services.settlement_service import _fingerprint, _canonical_json
        fp = _fingerprint(fp_parts)
        inputs = {"test": "data"}
        
        inserted = self.engine._insert_settlement_event(self.conn, 1, 101, eid, outcome, fp, inputs)
        self.assertTrue(inserted)
        
        # 4. Insert Settlement - Second Time (Idempotency)
        inserted_2 = self.engine._insert_settlement_event(self.conn, 1, 101, eid, outcome, fp, inputs)
        self.assertFalse(inserted_2, "Should return False on duplicate")
        
    def test_score_change_regrade(self):
        # 1. Setup Data (Same as above)
        eid = str(uuid.uuid4())
        self.conn.execute("INSERT INTO events_v2 (id, league) VALUES (?, ?)", (eid, "NCAAM"))
        # Initial Score: 80-70 (Home Won)
        self.conn.execute("INSERT INTO game_results (event_id, home_score, away_score, final) VALUES (?, 80, 70, 1)", (eid,))
        self.conn.execute("INSERT INTO bets (id, provider) VALUES (1, 'DK')")
        self.conn.execute("""
            INSERT INTO bet_legs (id, bet_id, event_id, leg_type, side, status) 
            VALUES (101, 1, ?, 'MONEYLINE', 'HOME', 'PENDING')
        """, (eid,))
        self.conn.commit()
        
        # Grade 1
        fp1_parts = [eid, "80", "70", "MONEYLINE", "HOME", "", self.engine.GRADING_VERSION]
        from src.services.settlement_service import _fingerprint
        fp1 = _fingerprint(fp1_parts)
        self.engine._insert_settlement_event(self.conn, 1, 101, eid, "WON", fp1, {})
        
        # 2. Update Score: Correction! Actually 60-70 (Home Lost)
        # Note: In real system, ingestion updates game_results.
        # Here we simulate finding a new result.
        
        # Grade 2
        # Result logic would fetch 60, 70
        fp2_parts = [eid, "60", "70", "MONEYLINE", "HOME", "", self.engine.GRADING_VERSION]
        fp2 = _fingerprint(fp2_parts)
        
        self.assertNotEqual(fp1, fp2)
        
        inserted_regrade = self.engine._insert_settlement_event(self.conn, 1, 101, eid, "LOST", fp2, {})
        self.assertTrue(inserted_regrade, "Should insert new event for score change")
        
        # Verify both exist
        cur = self.conn.execute("SELECT outcome FROM settlement_events WHERE leg_id=101")
        outcomes = [r[0] for r in cur.fetchall()]
        self.assertIn("WON", outcomes)
        self.assertIn("LOST", outcomes)

if __name__ == '__main__':
    unittest.main()
