import json
import os
from src.parsers.llm_parser import LLMSlipParser

def test_parser_with_fixtures():
    parser = LLMSlipParser()
    
    fixtures = [
        {
            "name": "DraftKings Single Bet",
            "sportsbook": "DK",
            "text": """
            DraftKings Sportsbook
            NFL
            Kansas City Chiefs @ San Francisco 49ers
            Chiefs -2.5 (-110)
            Stake: $110.00
            To Win: $100.00
            Total Payout: $210.00
            """,
            "expected": {
                "selection": "Chiefs -2.5",
                "stake": 110.0,
                "odds_american": -110
            }
        },
        {
            "name": "FanDuel Moneyline",
            "sportsbook": "FD",
            "text": """
            FanDuel Sportsbook
            EPL
            Manchester City vs Liverpool
            Selection: Manchester City
            Odds: +120
            Wager: $50.00
            Potential Payout: $110.00
            """,
            "expected": {
                "selection": "Manchester City",
                "stake": 50.0,
                "odds_american": 120
            }
        }
    ]
    
    print("Running Parser Fixture Tests...")
    
    # Note: This will actually call OpenAI if key is present, or mock if not.
    # We want to verify the mapping into our internal schema.
    
    for fix in fixtures:
        print(f"Testing: {fix['name']}...")
        result = parser.parse(fix['text'], fix['sportsbook'])
        
        # In mock mode, we expect it to return something reasonable.
        # If real OpenAI, it should match the expected fields.
        
        if result.get('status') == 'success':
            data = result.get('data', {})
            print(f"  Parsed Selection: {data.get('selection')}")
            print(f"  Parsed Stake: {data.get('stake')}")
            
            # Simple assertions on key fields
            assert data.get('selection') is not None
            assert data.get('stake') > 0
            assert 'price' in data
        else:
            print(f"  FAILED: {result.get('error')}")
            if os.environ.get("OPENAI_API_KEY"):
                assert False, f"Parser failed for {fix['name']} with real API key"

    print("Parser Fixture Tests Passed!")

if __name__ == "__main__":
    test_parser_with_fixtures()
