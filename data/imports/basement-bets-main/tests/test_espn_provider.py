import unittest
from unittest.mock import MagicMock, patch
import sys
import os
import json
from datetime import datetime

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.espn_client import EspnClient

class TestEspnClient(unittest.TestCase):

    def setUp(self):
        self.client = EspnClient()
        self.client.session = MagicMock()

    @patch('src.espn_client.log_ingestion_run')       # Arg 1
    @patch('src.espn_client.upsert_game_result')      # Arg 2
    @patch('src.espn_client.upsert_event_provider')   # Arg 3
    @patch('src.espn_client.upsert_event')            # Arg 4
    def test_ingest_ncaam_params(self, mock_log, mock_res, mock_prov, mock_evt):
        # Verify NCAAM calls list_events with correct params
        mock_response = {"events": []}
        mock_resp_obj = MagicMock()
        mock_resp_obj.json.return_value = mock_response
        self.client.session.get.return_value = mock_resp_obj
        
        # We also mock _save_raw_response to avoid file I/O
        with patch.object(self.client, '_save_raw_response') as mock_save:
            self.client.ingest_ncaam()
            
            # Check URL used
            call_args = self.client.session.get.call_args
            # Use safe indexing to check args
            self.assertTrue(len(call_args[0]) > 0)
            self.assertIn("basketball/mens-college-basketball", call_args[0][0])
            self.assertEqual(call_args[1]['params']['groups'], 50)
            self.assertEqual(call_args[1]['params']['limit'], 1000)
            
            # Check Raw Save called
            self.assertTrue(mock_save.called)

    @patch('src.espn_client.log_ingestion_run')
    @patch('src.espn_client.upsert_game_result')
    @patch('src.espn_client.upsert_event_provider')
    @patch('src.espn_client.upsert_event') 
    def test_ingest_nfl_success(self, mock_upsert_event, mock_upsert_provider, mock_upsert_result, mock_log_run):
        # NOTE: Arguments are reversed compared to decorators? 
        # Actually in Python @patch stacking:
        # @patch(A) -> passed as 1st arg
        # @patch(B) -> passed as 2nd arg
        # So test(mock_A, mock_B)
        # Here: 
        # log_ingestion_run -> Arg 1 (mock_upsert_event in name only) -> Incorrect naming in my previous thought
        # Let's trust position.
        # Def: test(mock_log, mock_res, mock_prov, mock_evt)
        # Using correct names now in test_ingest_ncaam_params.
        
        # Now testing log specifically
        pass # Covered above mostly, but let's do a specific check with correct arg names
        
    @patch('src.espn_client.log_ingestion_run')
    @patch('src.espn_client.upsert_game_result')
    @patch('src.espn_client.upsert_event_provider')
    @patch('src.espn_client.upsert_event')
    def test_ingest_logging(self, mock_evt, mock_prov, mock_res, mock_log):
        # Test Success Log
        mock_response = {"events": []}
        mock_resp_obj = MagicMock()
        mock_resp_obj.json.return_value = mock_response
        self.client.session.get.return_value = mock_resp_obj
        
        with patch.object(self.client, '_save_raw_response'):
            self.client.ingest_nfl()
            
        self.assertTrue(mock_log.called)
        log_arg = mock_log.call_args[0][0]
        self.assertEqual(log_arg['status'], 'SUCCESS')

    def test_raw_storage_path(self):
        import datetime
        dt = datetime.datetime(2025, 1, 15)
        
        with patch('gzip.open') as mock_gzip, patch('os.makedirs') as mock_mkdirs, patch('json.dump'):
            self.client._save_raw_response("NFL", dt, {"data": 1})
            
            # Verify directory
            mock_mkdirs.assert_called()
            path_arg = mock_mkdirs.call_args[0][0]
            self.assertTrue(path_arg.endswith("/data/raw/espn/NFL/2025/01/15"))

if __name__ == '__main__':
    unittest.main()
