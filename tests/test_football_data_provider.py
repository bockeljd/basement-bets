import unittest
from unittest.mock import MagicMock, patch
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.football_data_client import FootballDataClient

class TestFootballDataClient(unittest.TestCase):

    def setUp(self):
        # Initialize with dummy key to avoid warning
        self.client = FootballDataClient(api_key="test_key")
        self.client.session = MagicMock()
        # Disable rate limit delay for tests
        self.client._rate_limit_delay = 0

    @patch('src.football_data_client.log_ingestion_run')
    @patch('src.football_data_client.upsert_game_result')
    @patch('src.football_data_client.upsert_event_provider')
    @patch('src.football_data_client.upsert_event')
    def test_ingest_epl_success(self, mock_evt, mock_prov, mock_res, mock_log):
        # Mock API Response
        mock_data = {
            "matches": [
                {
                    "id": 123456,
                    "utcDate": "2024-03-10T15:00:00Z",
                    "status": "FINISHED",
                    "homeTeam": {"name": "Liverpool FC"},
                    "awayTeam": {"name": "Manchester City FC"},
                    "score": {
                        "fullTime": {"home": 1, "away": 1}
                    }
                }
            ]
        }
        
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_data
        self.client.session.get.return_value = mock_resp
        
        # Run Ingestion
        self.client.ingest_epl("2024-03-01", "2024-03-15")
        
        # Verify Upserts
        self.assertTrue(mock_evt.called)
        evt_args = mock_evt.call_args[0][0]
        self.assertEqual(evt_args['league'], 'EPL')
        self.assertEqual(evt_args['home_team'], 'Liverpool FC')
        self.assertEqual(evt_args['status'], 'final')
        
        self.assertTrue(mock_prov.called)
        prov_args = mock_prov.call_args[0][0]
        self.assertEqual(prov_args['provider'], 'football_data')
        self.assertEqual(str(prov_args['provider_event_id']), '123456')
        
        self.assertTrue(mock_res.called)
        res_args = mock_res.call_args[0][0]
        self.assertEqual(res_args['home_score'], 1)
        self.assertEqual(res_args['away_score'], 1)
        self.assertTrue(res_args['final_flag'])
        
        # Verify Logging
        self.assertTrue(mock_log.called)
        log_args = mock_log.call_args[0][0]
        self.assertEqual(log_args['items_count'], 1)
        self.assertEqual(log_args['status'], 'SUCCESS')

    def test_rate_limit_backoff(self):
        # Test handling of 429
        mock_429 = MagicMock()
        mock_429.status_code = 429
        
        mock_200 = MagicMock()
        mock_200.status_code = 200
        mock_200.json.return_value = {"matches": []}
        
        # First call retry, then success
        self.client.session.get.side_effect = [mock_429, mock_200]
        
        with patch('time.sleep') as mock_sleep:
            matches = self.client.fetch_matches("2024-03-01", "2024-03-02")
            
            # Should have slept for 60s
            mock_sleep.assert_called_with(60)
            # Should return empty list (from the second mock which returned empty matches)
            self.assertEqual(matches, [])
            # Should have called get twice
            self.assertEqual(self.client.session.get.call_count, 2)

if __name__ == '__main__':
    unittest.main()
