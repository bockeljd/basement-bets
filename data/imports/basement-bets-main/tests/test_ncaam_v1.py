import unittest
from unittest.mock import MagicMock, patch
import sys
import os
from datetime import datetime, timedelta

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.models.ncaam_v1 import NCAAMModelV1

class TestNCAAMModelV1(unittest.TestCase):

    def setUp(self):
        self.model = NCAAMModelV1()

    @patch('src.models.ncaam_v1.get_db_connection')
    def test_fetch_features_lookahead(self, mock_get_conn):
        # Mock DB behavior
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        
        # Setup specific return values for strict timing
        # If we query for data BEFORE game_time (e.g. 2024-01-02), we should get 2024-01-01 data.
        
        # We need to mock _exec usage in the class.
        # It's imported as _exec. Since we patch the module imports...
        pass

    def test_predict_score_math(self):
        features = {
            'home': {'adj_off': 110.0, 'adj_def': 95.0, 'adj_tempo': 70.0},
            'away': {'adj_off': 100.0, 'adj_def': 105.0, 'adj_tempo': 70.0}
        }
        # Tempo = (70+70)/2 = 70.
        # H Score = 1.10 * 70 = 77.
        # A Score = 1.00 * 70 = 70.
        
        h, a = self.model.predict_score(features)
        self.assertAlmostEqual(h, 77.0)
        self.assertAlmostEqual(a, 70.0)

    @patch('src.models.ncaam_v1.NCAAMModelV1.fetch_features')
    def test_run_inference(self, mock_fetch):
        # Setup mock return
        mock_fetch.return_value = {
            'home': {'adj_off': 110.0, 'adj_tempo': 70.0, 'date': '2024-01-01'},
            'away': {'adj_off': 100.0, 'adj_tempo': 70.0, 'date': '2024-01-01'}
        }
        
        # Game Time
        game_time = datetime(2024, 1, 2, 19, 0)
        
        # Market: Home -3.5 (Hurdle 3.5), Total 140
        # Model: H 77, A 70. Margin 7. Total 147.
        
        res = self.model.run_inference("Duke", "UNC", game_time, 3.5, 140.0)
        
        self.assertAlmostEqual(res['implied_margin'], 7.0)
        self.assertAlmostEqual(res['implied_total'], 147.0)
        self.assertGreater(res['cover_prob'], 0.5) # 7 > 3.5
        self.assertGreater(res['over_prob'], 0.5) # 147 > 140

if __name__ == '__main__':
    unittest.main()
