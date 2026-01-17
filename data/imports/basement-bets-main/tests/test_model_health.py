import unittest
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.model_health import ModelHealth

class TestModelHealth(unittest.TestCase):

    def setUp(self):
        self.health = ModelHealth()

    def test_brier_score(self):
        # Pred 0.8, Result 1 -> (0.2)^2 = 0.04
        # Pred 0.6, Result 0 -> (0.6)^2 = 0.36
        # Mean = 0.40 / 2 = 0.20
        preds = [
            {'prob': 0.8, 'outcome': 1},
            {'prob': 0.6, 'outcome': 0}
        ]
        brier = self.health.compute_brier(preds)
        self.assertAlmostEqual(brier, 0.20)

    def test_ece_perfect(self):
        # Perfect calibration
        preds = []
        # Bin 0.8: 5 wins, 5 losses is uncalibrated. 8 wins, 2 losses is calibrated.
        for _ in range(8): preds.append({'prob': 0.8, 'outcome': 1})
        for _ in range(2): preds.append({'prob': 0.8, 'outcome': 0})
        
        # Bin 0.2: 2 wins, 8 losses.
        for _ in range(2): preds.append({'prob': 0.2, 'outcome': 1})
        for _ in range(8): preds.append({'prob': 0.2, 'outcome': 0})
        
        ece = self.health.compute_ece(preds, n_bins=10)
        # Avg Prob Bin 0.8 = 0.8. Avg Outcome = 0.8. Diff = 0.
        # Avg Prob Bin 0.2 = 0.2. Avg Outcome = 0.2. Diff = 0.
        self.assertAlmostEqual(ece, 0.0)

    def test_promotion_logic(self):
        cand = {'brier': 0.18, 'ece': 0.03}
        incumb = {'brier': 0.20, 'ece': 0.04}
        
        # Better Brier, Good ECE -> Promote
        self.assertTrue(self.health.check_promotion(cand, incumb))
        
        # Better Brier, Bad ECE -> Reject
        cand_bad = {'brier': 0.18, 'ece': 0.15}
        self.assertFalse(self.health.check_promotion(cand_bad, incumb))
        
        # Worse Brier -> Reject
        cand_worse = {'brier': 0.22, 'ece': 0.01}
        self.assertFalse(self.health.check_promotion(cand_worse, incumb))

if __name__ == '__main__':
    unittest.main()
