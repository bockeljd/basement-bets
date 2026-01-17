import unittest
from unittest.mock import MagicMock, patch
import sys
import os
from datetime import datetime

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.models.epl_v1 import EPLModelV1

class TestEPLModelV1(unittest.TestCase):

    def setUp(self):
        self.model = EPLModelV1()

    def test_calculate_strengths(self):
        # Mock history
        # League Avg = 2.5 (1.25 per team)
        # Team A scores 2.5 avg, concedes 1.25
        # Team B scores 1.25, concedes 1.25
        
        history = []
        # Create 10 games for Team A where they score 2, concede 1
        for _ in range(10):
            history.append({'home_team': 'Team A', 'away_team': 'Other', 'home_score': 2, 'away_score': 1})
        # Create 10 games for Team B where they score 1, concede 1
        for _ in range(10):
            history.append({'home_team': 'Team B', 'away_team': 'Other', 'home_score': 1, 'away_score': 1})
            
        # Total goals = 30 + 20 = 50. Games = 20. Avg = 2.5. Avg/Team = 1.25.
        
        h_att, h_def, a_att, a_def, l_avg = self.model.calculate_strengths(history, 'Team A', 'Team B')
        
        # Team A Att: (2.0) / 1.25 = 1.6
        # Team A Def: (1.0) / 1.25 = 0.8
        # Team B Att: (1.0) / 1.25 = 0.8
        # Team B Def: (1.0) / 1.25 = 0.8
        
        self.assertAlmostEqual(l_avg, 1.25)
        # Check shrinkage (0.1 means 90% of value + 10% of 1)
        expected_h_att = 1.6 * 0.9 + 0.1
        self.assertAlmostEqual(h_att, expected_h_att)

    def test_poisson_logic(self):
        # Lambda = 1.0. P(0) = 1^0 * e^-1 / 1 = 0.367
        p = self.model._poisson_prob(1.0, 0)
        self.assertAlmostEqual(p, 0.367879, places=5)

    @patch('src.models.epl_v1.EPLModelV1.fetch_history')
    def test_run_inference(self, mock_fetch):
        # Basic smoke test for probability summing
        mock_fetch.return_value = [] # Yields defaults 1.0 strengths
        
        res = self.model.run_inference('Man City', 'Liverpool', datetime.now())
        
        # With default strengths 1.0 and avg 1.35 (fallback) and home adv 1.2
        # Lambda H = 1*1*1.35*1.2 = 1.62
        # Lambda A = 1*1*1.35 = 1.35
        # H should be favored
        self.assertGreater(res['win_prob'], res['away_prob'])
        
        total = res['win_prob'] + res['draw_prob'] + res['away_prob']
        self.assertAlmostEqual(total, 1.0, places=2)

if __name__ == '__main__':
    unittest.main()
