import unittest
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.models.nfl_v1 import NFLModelV1

class TestNFLModelV1(unittest.TestCase):

    def setUp(self):
        self.model = NFLModelV1(sigma_margin=13.5, sigma_total=11.0)

    def test_win_probability_even_matchup(self):
        # Even matchup (margin 0) vs Pick'em (spread 0)
        # Should be 50/50
        p_win, p_cover, _ = self.model.predict_margin_probs(0.0, 0.0)
        self.assertAlmostEqual(p_win, 0.5, places=2)
        self.assertAlmostEqual(p_cover, 0.5, places=2)

    def test_win_probability_favorite(self):
        # Projected Margin +7.0 (Home wins by 7)
        # Market Spread +3.5 (Home -3.5, so hurdle is 3.5)
        # Z = (3.5 - 7.0) / 13.5 = -3.5 / 13.5 = -0.259
        # CDF(-0.259) approx 0.40 -> Cover Prob approx 0.60
        
        p_win, p_cover, _ = self.model.predict_margin_probs(7.0, 3.5)
        
        # Win prob (margin > 0)
        # Z = (0 - 7) / 13.5 = -0.518
        # CDF(-0.518) approx 0.30 -> Win Prob approx 0.70
        self.assertGreater(p_win, 0.65)
        self.assertGreater(p_cover, 0.55) # Should beat the spread since 7 > 3.5
        
    def test_total_probability(self):
        # Projected 50, Market 45
        # Should be Over
        p_over, p_under = self.model.predict_total_probs(50.0, 45.0)
        self.assertGreater(p_over, 0.6)
        self.assertAlmostEqual(p_over + p_under, 1.0, places=5)

    def test_inference_integration(self):
        data = {
            'projected_home_score': 24.0,
            'projected_away_score': 20.0,
            'market_spread_hurdle': 3.5, # Home -3.5
            'market_total_hurdle': 45.0
        }
        output = self.model.run_inference(data)
        
        # Margin = 4.0. Spread = 3.5. Slight edge.
        self.assertGreater(output['cover_prob'], 0.5)
        self.assertAlmostEqual(output['implied_margin'], 4.0)

if __name__ == '__main__':
    unittest.main()
