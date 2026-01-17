import unittest
import sqlite3
import shutil
import os
import sys

# Path hack
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.services.settlement_service import SettlementEngine
from src.database import get_db_connection, _exec

class TestSettlement(unittest.TestCase):
    
    def setUp(self):
        # Setup Test DB
        # We rely on src.database using 'bets.db' or we can override settings?
        # Ideally we'd mock the connection, but integeration test with SQLite is fine.
        # Let's assume we can run safely locally if we back up or use a separate file.
        # But `src.database` hardcodes `bets.db`.
        # Strategy: Rely on logic only? No, SettlementEngine calls DB.
        # I'll rely on the fact that I'm in a verification phase. 
        # Actually, I should create a mock subclass of SettlementEngine OR override DB_PATH logic??
        # I will override `src.database.DB_PATH` if possible or just use a mock connection.
        pass

    def test_grading_logic(self):
        # Unit test the _grade_leg method directly (it is pure logic mostly given the dict)
        engine = SettlementEngine()
        
        # Scenario 1: ML Win (Home)
        leg_ml_win = {
            'leg_id': 1, 'selection': 'Chiefs', 'leg_type': 'MONEYLINE',
            'home_name': 'Chiefs', 'away_name': 'Raiders', 
            'home_score': 30, 'away_score': 10, 'line_value': 0
        }
        outcome, _ = engine._grade_leg(leg_ml_win)
        self.assertEqual(outcome, 'WON')

        # Scenario 2: Spread Loss (Home -7.5, won by 3)
        leg_spread_loss = {
            'leg_id': 2, 'selection': 'Chiefs -7.5', 'leg_type': 'SPREAD',
            'home_name': 'Chiefs', 'away_name': 'Raiders', 
            'home_score': 13, 'away_score': 10, 'line_value': -7.5
        }
        outcome, _ = engine._grade_leg(leg_spread_loss)
        # 13 + -7.5 = 5.5 < 10 -> LOST
        self.assertEqual(outcome, 'LOST')
        
        # Scenario 3: Total Push (Over 40, Score 20-20)
        leg_push = {
            'leg_id': 3, 'selection': 'Over 40', 'leg_type': 'TOTAL',
            'home_name': 'A', 'away_name': 'B',
            'home_score': 20, 'away_score': 20, 'line_value': 40
        }
        outcome, _ = engine._grade_leg(leg_push)
        self.assertEqual(outcome, 'PUSH')

if __name__ == '__main__':
    unittest.main()
