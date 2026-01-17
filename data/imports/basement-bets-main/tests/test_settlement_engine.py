import unittest
from unittest.mock import MagicMock, patch
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.settlement_engine import SettlementEngine

class TestSettlementEngine(unittest.TestCase):

    def setUp(self):
        self.engine = SettlementEngine()

    @patch('src.settlement_engine.update_model_prediction_result')
    def test_grade_moneyline_win(self, mock_update):
        pred = {
            'id': 1,
            'sport': 'NFL',
            'bet_on': 'Team A',
            'home_team': 'Team A',
            'away_team': 'Team B',
            'market': 'Moneyline',
            'market_line': 0
        }
        result = {
            'final_flag': True,
            'status': 'final',
            'home_score': 24,
            'away_score': 10
        }
        
        grading = self.engine._grade_prediction(pred, result)
        self.assertEqual(grading['status'], 'Win')

    @patch('src.settlement_engine.update_model_prediction_result')
    def test_grade_spread_win(self, mock_update):
        # Bet: Team B +7.5
        # Result: Team A 20 - 14 Team B.
        # Team B score (14) + 7.5 = 21.5 > Team A (20). WIN.
        pred = {
            'id': 2,
            'sport': 'NFL',
            'bet_on': 'Team B',
            'home_team': 'Team A',
            'away_team': 'Team B',
            'market': 'Spread',
            'market_line': 7.5
        }
        result = {
            'final_flag': True,
            'status': 'final',
            'home_score': 20,
            'away_score': 14
        }
        grading = self.engine._grade_prediction(pred, result)
        self.assertEqual(grading['status'], 'Win')

    def test_grade_spread_push(self):
        # Bet: Team A -3
        # Result: Team A 20 - 17 Team B
        # Team A (20) + (-3) = 17 == Team B (17). PUSH.
        pred = {
            'id': 3,
            'sport': 'NFL',
            'bet_on': 'Team A',
            'home_team': 'Team A',
            'away_team': 'Team B',
            'market': 'Spread',
            'market_line': -3.0
        }
        result = {
            'final_flag': True,
            'status': 'final',
            'home_score': 20,
            'away_score': 17
        }
        grading = self.engine._grade_prediction(pred, result)
        self.assertEqual(grading['status'], 'Push')

    def test_grade_over_under_loss(self):
        # Bet: Under 45
        # Result: 24 + 24 = 48. LOSS.
        pred = {
            'id': 4,
            'sport': 'NFL',
            'bet_on': 'Under 45',
            'home_team': 'Team A',
            'away_team': 'Team B',
            'market': 'Total',
            'market_line': 45.0
        }
        result = {
            'final_flag': True,
            'status': 'final',
            'home_score': 24,
            'away_score': 24
        }
        grading = self.engine._grade_prediction(pred, result)
        self.assertEqual(grading['status'], 'Loss')

    def test_calculate_metrics(self):
        # Mock bets for metrics
        bets = [
            {'result': 'Win', 'result_prob': 0.55}, # Win (1)
            {'result': 'Loss', 'result_prob': 0.60}, # Loss (0)
            {'result': 'Push', 'result_prob': 0.50}  # Ignore
        ]
        # Brier: (0.5-1)^2 + (0.5-0)^2 = 0.25 + 0.25 = 0.5 / 2 = 0.25
        # (Assuming prob is 0.5 in code default)
        
        metrics = self.engine._compute_metrics_batch(bets)
        self.assertAlmostEqual(metrics['brier_score'], 0.25)
        self.assertEqual(metrics['count_bets'], 3)

if __name__ == '__main__':
    unittest.main()
