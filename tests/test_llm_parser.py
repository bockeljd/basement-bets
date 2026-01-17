
import unittest
from src.parsers.llm_parser import LLMSlipParser

class TestLLMSlipParser(unittest.TestCase):
    def test_mock_response_structure(self):
        parser = LLMSlipParser()
        # Force mock by unsetting API key if present, or just calling mock directly?
        # The code checks `if not self.api_key`.
        # We can temporarily unset it or inject a mock.
        parser.api_key = None
        
        raw_text = """
        Wager: $50
        Kansas -4.5 (-110)
        vs Iowa State
        """
        result = parser.parse(raw_text, "DK")
        
        print(result)
        
        self.assertIn("stake", result)
        self.assertEqual(result['stake'], 50.0)
        self.assertEqual(result['market_type'], "SPREAD")
        self.assertIn("normalized_team", result.get("legs", [{}])[0])
        # Mock returns "normalized_team"? 
        # Wait, the mock implementation in the file needs to be updated to match the new schema!
        # The mock in the file has "selection" but maybe not "legs" with full detail.
        # I should check the mock implementation in the file.

if __name__ == '__main__':
    unittest.main()
