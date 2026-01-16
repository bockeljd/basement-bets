import unittest
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.settlement_engine import SettlementEngine

class TestSettlementParlays(unittest.TestCase):

    def setUp(self):
        self.engine = SettlementEngine()

    def test_parlay_all_won(self):
        legs = [
            {'status': 'WON'},
            {'status': 'WON'},
            {'status': 'WON'}
        ]
        self.assertEqual(self.engine.grade_bet_slip(legs), 'WON')

    def test_parlay_one_loss(self):
        legs = [
            {'status': 'WON'},
            {'status': 'LOST'}, # Killer leg
            {'status': 'WON'}
        ]
        self.assertEqual(self.engine.grade_bet_slip(legs), 'LOST')

    def test_parlay_pending(self):
        legs = [
            {'status': 'WON'},
            {'status': 'PENDING'},
            {'status': 'WON'}
        ]
        self.assertEqual(self.engine.grade_bet_slip(legs), 'PENDING')

    def test_parlay_with_push(self):
        # Won + Push -> Won (Reduced Odds usually, but status is WON)
        legs = [
            {'status': 'WON'},
            {'status': 'PUSH'}
        ]
        self.assertEqual(self.engine.grade_bet_slip(legs), 'WON')

    def test_parlay_all_push(self):
        legs = [
            {'status': 'PUSH'},
            {'status': 'VOID'}
        ]
        self.assertEqual(self.engine.grade_bet_slip(legs), 'PUSH')

if __name__ == '__main__':
    unittest.main()
