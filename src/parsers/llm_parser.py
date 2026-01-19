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
  "market_type": "string", // [ML, Over/Under, SPREAD, PROP, {N} leg parlay]
  "is_parlay": boolean,
  "confidence": float, // 0.0 to 1.0
  "status": "string", // [WON, LOST, PENDING, CASHED OUT]
  "sport": "string", // [NFL, NBA, NCAAM, MLB, NHL, SOCCER, etc.]
  "placed_at": "string", // ISO-8601 or YYYY-MM-DD HH:MM:SS if found
  "event_name": "string", // MATCHUP (e.g. "Kansas City Chiefs vs Buffalo Bills")
  "selection": "string", // The specific bet selection (e.g. Chiefs -3.5)
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
   - Market Types: Use "ML" for Moneyline, "Over/Under" for totals, "SPREAD" for point spreads, "PROP" for player props.
   - Parlays: Use "{N} leg parlay" (e.g., "3 leg parlay", "12 leg parlay").
   - Sport: MUST be one of [NFL, NBA, NCAAM, MLB, NHL, SOCCER, NCAAF]. Do NOT use "Basketball" or "Football", use the league/level code.
   - Matchup: "event_name" MUST be the teams playing (e.g., "Lakers vs Celtics"). If not found, infer from selection.
   - Status: Extract status if explicitly mentioned (e.g. "Won", "Lost"). Default to "PENDING" if unclear.
   - Date: Find the placement date/time. If only date is found, use it.
3. PARLAYS: If multiple selections exist, treat as PARLAY or SGP.
4. CONFIDENCE: < 0.8 if critical fields (stake, selection, teams) are ambiguous.
"""

    def parse(self, text: str, sportsbook: str) -> Dict[str, Any]:
        """
        Parses raw slip text using OpenAI with local fallbacks for DraftKings and FanDuel.
        """
        # 1. Try OpenAI Parser first if API key is present
        if self.api_key:
            try:
                from openai import OpenAI
                client = OpenAI(api_key=self.api_key)
                response = client.chat.completions.create(
                    model="gpt-4-turbo-preview",
                    messages=[
                        {"role": "system", "content": self.get_system_prompt()},
                        {"role": "user", "content": f"Sportsbook: {sportsbook}\n\nText:\n{text}"}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0
                )
                
                result = json.loads(response.choices[0].message.content)
                # Ensure core fields
                if 'status' not in result: result['status'] = 'PENDING'
                if 'sport' not in result: result['sport'] = 'Unknown'
                if 'placed_at' not in result: result['placed_at'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                # Confidence check: if it's very low, maybe fall back to regex if it's a known format
                if result.get('confidence', 1.0) >= 0.7:
                    result['parser_version'] = self.version
                    result['raw_hash'] = hashlib.sha256(text.encode()).hexdigest()
                    result['raw_text'] = text
                    return result
                    
            except Exception as e:
                print(f"[Parser] OpenAI Error, attempting fallback: {e}")

        # 2. Local Fallbacks (Works without API key or as secondary for structured text)
        if sportsbook == "DK":
            try:
                from src.parsers.draftkings_text import DraftKingsTextParser
                dk_parser = DraftKingsTextParser()
                dk_bets = dk_parser.parse(text)
                if dk_bets:
                    b = dk_bets[0]
                    bt_up = b['bet_type'].upper()
                    return {
                        "stake": b['wager'],
                        "price": {"american": b['odds'], "decimal": 0}, 
                        "market_type": b['bet_type'].upper(),
                        "is_parlay": any(x in bt_up for x in ["PARLAY", "SGP", "LEG"]),
                        "confidence": 1.0,
                        "status": b['status'],
                        "sport": b['sport'],
                        "event_name": b.get('description', 'DraftKings Bet'),
                        "selection": b['selection'],
                        "placed_at": b['date'],
                        "legs": [{"selection": b['selection'], "odds_american": b['odds']}],
                        "missing_fields": [],
                        "raw_hash": hashlib.sha256(text.encode()).hexdigest(),
                        "parser_version": "dk-regex-v1",
                        "raw_text": text
                    }
            except Exception as e:
                print(f"[Parser] DK Fallback failed: {e}")

        if sportsbook == "FD" or sportsbook == "FanDuel":
            try:
                from src.parsers.fanduel import FanDuelParser
                fd_parser = FanDuelParser()
                fd_bets = fd_parser.parse(text)
                if fd_bets:
                    b = fd_bets[0]
                    bt_up = b['bet_type'].upper()
                    return {
                        "stake": b['wager'],
                        "price": {"american": b['odds'], "decimal": 0},
                        "market_type": b['bet_type'].upper(),
                        "is_parlay": any(x in bt_up for x in ["PARLAY", "SGP", "ROUND ROBIN", "LEG"]),
                        "confidence": 1.0,
                        "status": b['status'],
                        "sport": b['sport'],
                        "event_name": b.get('description', 'FanDuel Bet'),
                        "selection": b['selection'],
                        "placed_at": b['date'],
                        "legs": [{"selection": b['selection'], "odds_american": b['odds']}],
                        "missing_fields": [],
                        "raw_hash": hashlib.sha256(text.encode()).hexdigest(),
                        "parser_version": "fd-regex-v1",
                        "raw_text": text
                    }
            except Exception as e:
                print(f"[Parser] FD Fallback failed: {e}")

        # If no API key and no regex hit
        if not self.api_key:
             return self._get_mock_response(text, sportsbook)

        return {"error": "Unable to parse slip", "confidence": 0, "raw_text": text}

    def _get_mock_response(self, text, sportsbook):
        """Dev fallback for local testing."""
        return {
            "stake": 50.00,
            "price": {"american": -110, "decimal": 1.91},
            "market_type": "SPREAD",
            "is_parlay": False,
            "confidence": 0.95,
            "event_name": "Kansas vs Baylor",
            "selection": "Kansas -4.5",
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
            "parser_version": self.version + "-mock",
            "raw_text": text
        }
