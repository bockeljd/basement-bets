from typing import Dict, List, Any, Optional
from src.models.ncaam_model import NCAAMModel
from src.services.barttorvik import BartTorvikClient
from src.services.odds_fetcher_service import OddsFetcherService

class NCAAMMarketFirstModel:
    """
    NCAAM Market-First Model Wrapper.
    Prioritizes market lines and blends with model signal.
    """
    
    def __init__(self):
        self.model = NCAAMModel()
        self.torvik = BartTorvikClient()
        self.odds_service = OddsFetcherService()

    def analyze_game(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """
        Runs the market-first analysis for a single NCAAM event.
        """
        home_team = event.get('home_team')
        away_team = event.get('away_team')
        
        # 1. Fetch Market Context (Odds)
        # 1. Fetch Market Context (Odds)
        from src.database import get_last_prestart_snapshot
        
        event_id = event.get('id')
        market_spread = None
        market_total = None
        
        # Helper to find best available line
        def get_best_line(snapshots, side_needed):
            # Simple heuristic: take the first one (latest due to sort order)
            # In a real system, might want median or specific book filter
            for s in snapshots:
                if s['side'].upper() == side_needed.upper():
                    return s['line']
            return None

        # Fetch Spread
        spread_snaps = get_last_prestart_snapshot(event_id, "SPREAD")
        if spread_snaps:
             # We want the spread from HOME perspective.
             # If side is HOME, spread is X. If side is AWAY, spread is usually -X (but check logic).
             # Standard: Home -5.5 means Home needs to win by 6.
             # Snapshots store side & line.
             # If we find a HOME line, use it.
             market_spread = get_best_line(spread_snaps, "HOME")
             if market_spread is None:
                 # Try Away and invert? Or just rely on coverage.
                 # Usually spreads are symmetric -110/-110 but values might differ slightly.
                 away_line = get_best_line(spread_snaps, "AWAY")
                 if away_line is not None:
                     market_spread = -away_line

        # Fetch Total
        total_snaps = get_last_prestart_snapshot(event_id, "TOTAL")
        if total_snaps:
            market_total = get_best_line(total_snaps, "OVER") # Total is usually same for Over/Under

        
        # 2. Fetch Model Signal (Torvik)
        official_projections = self.torvik.fetch_daily_projections()
        home_proj = official_projections.get(home_team) or official_projections.get(self.model.standardize_team_name(home_team))
        
        torvik_spread = None
        torvik_total = None
        
        if home_proj:
            torvik_spread = home_proj.get('spread')
            torvik_total = home_proj.get('total')
            
        # 3. Blend Logic (70/30)
        final_spread = None
        blend_note = ""
        
        if market_spread is not None:
            if torvik_spread is not None:
                final_spread = (market_spread * 0.7) + (torvik_spread * 0.3)
                blend_note = f"Market ({market_spread}) weighted 70%, Torvik ({torvik_spread}) weighted 30%."
            else:
                final_spread = market_spread
                blend_note = "Using Market prior (Model signal unavailable)."
        else:
            final_spread = torvik_spread
            blend_note = "Using Model signal only (Market line unavailable)."
            
        # 4. Results & Recommendations
        recs = []
        if final_spread is not None:
            pick = home_team if final_spread < 0 else away_team
            recs.append({
                "bet_type": "Spread",
                "selection": f"{pick} {'-' if final_spread < 0 else '+'}{abs(final_spread):.1f}",
                "market_line": market_spread,
                "fair_line": round(final_spread, 1),
                "edge": round(abs(final_spread - (market_spread or 0)), 1),
                "confidence": "Medium",
                "reasoning": f"Weighted blend of market and efficiency metrics. {blend_note}"
            })
            
        return {
            "recommendations": recs,
            "narrative": f"Analysis complete for {away_team} @ {home_team}. {blend_note}",
            "key_factors": [blend_note, f"Home Court: {home_team}"],
            "risks": ["Standard market variance", "Injuries not fully accounted for"],
            "model_details": {
                "market_spread": market_spread,
                "torvik_spread": torvik_spread,
                "blend_ratio": "70/30"
            }
        }
