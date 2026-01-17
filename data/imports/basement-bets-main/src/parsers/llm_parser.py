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
        return """You are a Senior Betting Data Analyst specializing in parsing unformatted betting slips from DraftKings (DK) and FanDuel (FD). 

GOAL: Convert raw text into a valid JSON object following the provided schema.

RULES:
1. DETERMINISM: Only return the JSON object. No explanation, no markdown text outside the JSON.
2. NORMALIZATION:
   - Market Types: Convert to "ML", "SPREAD", "TOTAL", or "PROP".
   - Sport Keys: Use TheOddsAPI style (e.g., basketball_ncaab, americanfootball_nfl, soccer_epl).
   - Odds: Calculate decimal odds if American odds are provided.
3. PARLAYS: If the slip contains multiple legs, populate the 'legs' array and set 'is_parlay': true.
4. STANDARDIZATION: Keep the 'raw_selection' exactly as found, but provide a 'normalized_selection' using standard team full names.
5. CONFIDENCE: Set a confidence score from 0 to 1. If fields like stake or selection are missing, list them in 'missing_fields'.

ERROR HANDLING:
- If the text is completely unreadable, return {"error": "unsupported_format", "confidence": 0}.
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
            "parser_version": self.version + "-mock",
            "sportsbook": sportsbook,
            "placed_at": "2024-01-14T12:00:00Z",
            "stake": 50.00,
            "price": {"american": -110, "decimal": 1.91},
            "market_type": "SPREAD",
            "selection": "Kansas Jayhawks",
            "line": -4.5,
            "event_name": "Kansas Jayhawks vs Iowa State Cyclones",
            "sport": "basketball_ncaab",
            "legs": [],
            "confidence": 0.95,
            "missing_fields": [],
            "is_parlay": False,
            "raw_hash": hashlib.sha256(text.encode()).hexdigest()
        }
