"""
GameAnalyzer Service

Single-game analysis engine that:
1. Resolves event context from canonical 'events' table
2. Runs sport-specific model wrappers
3. Generates betting narrative and persists to history
"""
from typing import Dict, List, Optional, Any
from datetime import datetime
from src.database import get_db_connection, _exec, insert_model_prediction

class GameAnalyzer:
    """
    Run analysis for a single game based on its canonical event ID.
    """
    
    def analyze(self, game_id: str, sport: str, home_team: str, away_team: str) -> Dict[str, Any]:
        """
        Main analysis entry point.
        """
        print(f"[GameAnalyzer] Analyzing {away_team} @ {home_team} ({sport}) - ID: {game_id}")
        
        # 1. Fetch Event Context (Standardized on 'events')
        # Wrapping in retry logic for DB stability
        max_retries = 2
        last_error = None
        
        for attempt in range(max_retries):
            try:
                event = self._fetch_event_context(game_id)
                if not event:
                    # Fallback if ID lookup fails (legacy or mismatch)
                    event = {
                        "id": game_id,
                        "sport": sport,
                        "home_team": home_team,
                        "away_team": away_team,
                        "league": sport
                    }

                # 2. Run Sport-Specific Analysis
                if sport == "NCAAM":
                    from src.models.ncaam_market_first_model_v2 import NCAAMMarketFirstModelV2
                    model_wrapper = NCAAMMarketFirstModelV2()
                    result = model_wrapper.analyze(event_id=game_id)
                elif sport == "NFL":
                    result = self._analyze_nfl(home_team, away_team)
                elif sport == "EPL":
                    result = self._analyze_epl(home_team, away_team)
                else:
                    result = self._analyze_generic(home_team, away_team, sport)
                
                # 3. Enrich and Persist
                result["game_id"] = game_id
                result["sport"] = sport
                result["matchup"] = f"{away_team} @ {home_team}"
                result["home_team"] = home_team
                result["away_team"] = away_team
                result["analyzed_at"] = datetime.now().isoformat()
                
                self._persist_analysis(result)
                
                return result
                
            except Exception as e:
                last_error = e
                print(f"[GameAnalyzer] Analysis attempt {attempt + 1} failed: {e}")
                import time
                if attempt < max_retries - 1:
                    time.sleep(0.5) # Short backoff
        
        # If we get here, all retries failed
        print(f"[GameAnalyzer] Critical Failure: Analysis failed after {max_retries} attempts.")
        raise last_error

    def _fetch_event_context(self, event_id: str) -> Optional[Dict[str, Any]]:
        """Fetch canonical event row from the 'events' table."""
        query = "SELECT * FROM events WHERE id = :id"
        with get_db_connection() as conn:
            cursor = _exec(conn, query, {"id": event_id})
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None

    def _persist_analysis(self, result: Dict[str, Any]):
         # Persistence is now primarily handled inside the model.analyze method 
         # to capture all internal mu/sigma/inputs.
         pass

    def _analyze_nfl(self, home_team: str, away_team: str) -> Dict[str, Any]:
        """NFL Placeholder (TODO: Move to market-first wrapper)"""
        return {
            "recommendations": [],
            "narrative": "NFL analysis requires new market-first wrapper implementation.",
            "key_factors": [],
            "risks": []
        }

    def _analyze_epl(self, home_team: str, away_team: str) -> Dict[str, Any]:
        """EPL Placeholder (TODO: Move to market-first wrapper)"""
        return {
            "recommendations": [],
            "narrative": "EPL analysis requires new market-first wrapper implementation.",
            "key_factors": [],
            "risks": []
        }

    def _analyze_generic(self, home_team: str, away_team: str, sport: str) -> Dict[str, Any]:
        """Generic fallback"""
        return {
            "recommendations": [],
            "narrative": f"Analysis for {sport} is not yet supported. Check back soon!",
            "key_factors": [],
            "risks": []
        }
