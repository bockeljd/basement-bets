import os
import json
import hashlib
from typing import Dict, Any
import openai

class LLMSlipParser:
    def __init__(self):
        self.api_key = os.environ.get("OPENAI_API_KEY")
        if self.api_key:
            openai.api_key = self.api_key
        
        self.version = "2024-01-14v1"

    def get_system_prompt(self):
        return """You are a Senior Betting Data Analyst specializing in parsing unformatted betting slips from DraftKings (DK), FanDuel (FD), and Caesar's.

GOAL: Convert raw text into a valid JSON object following the strict schema below.

SCHEMA:
{
  "stake": float, // The wager amount
  "price": {"american": int, "decimal": float}, // Extracted odds
  "market_type": "string", // [ML, SPREAD, TOTAL, PROP, PARLAY]
  "is_parlay": boolean,
  "confidence": float, // 0.0 to 1.0
  "legs": [
    {
       "selection": "string", // Raw selection text
       "normalized_player": "string" or null, // "First Last"
       "normalized_team": "string" or null, // "Team Name"
       "line_value": float or null, // e.g. -4.5, 212.5
       "market_key": "string", // Normalised market key
       "odds_american": int // Odds for this leg if available
    }
  ],
  "missing_fields": ["string"]
}

RULES:
1. DETERMINISM: Only return the JSON object. No markdown.
2. NORMALIZATION:
   - Market Types: "ML" for Moneyline, "SPREAD" for Point Spreads, "TOTAL" for Over/Under, "PROP" for Player Props.
   - Sport Keys: Infer context if possible, otherwise leave generic.
   - Player Names: Convert "L. James" to "LeBron James" if confident.
3. PARLAYS: If multiple selections exist, treat as PARLAY.
4. CONFIDENCE: < 0.8 if critical fields (stake, selection) are ambiguous.
"""

    def parse(self, text: str, sportsbook: str) -> Dict[str, Any]:
        """
        Parses raw slip text using OpenAI.
        """
        if not self.api_key:
            # Mock response for dev when API key is missing
            return self._get_mock_response(text, sportsbook)

        try:
            response = openai.ChatCompletion.create(
                model="gpt-4-turbo-preview",
                messages=[
                    {"role": "system", "content": self.get_system_prompt()},
                    {"role": "user", "content": f"Sportsbook: {sportsbook}\n\nText:\n{text}"}
                ],
                response_format={"type": "json_object"},
                temperature=0
            )
            
            result = json.loads(response.choices[0].message.content)
            result['parser_version'] = self.version
            result['raw_hash'] = hashlib.sha256(text.encode()).hexdigest()
            return result
        except Exception as e:
            print(f"[Parser] OpenAI Error: {e}")
            return {"error": str(e), "confidence": 0}

    def _get_mock_response(self, text, sportsbook):
        """Dev fallback for local testing."""
        return {
            "snake_case_conversion_active": True,
            "stake": 50.00,
            "price": {"american": -110, "decimal": 1.91},
            "market_type": "SPREAD",
            "is_parlay": False,
            "confidence": 0.95,
            "legs": [
                {
                    "selection": "Kansas Jayhawks",
                    "normalized_team": "Kansas",
                    "normalized_player": None,
                    "line_value": -4.5,
                    "market_key": "spread",
                    "odds_american": -110
                }
            ],
            "missing_fields": [],
            "raw_hash": hashlib.sha256(text.encode()).hexdigest(),
            "parser_version": self.version + "-mock"
        }
