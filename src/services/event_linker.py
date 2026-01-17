from typing import Dict, Optional, Tuple
from src.services.event_resolver import EventResolver

class EventLinker:
    """
    High-level service to link bet legs to canonical events with confidence policies.
    """
    
    def __init__(self):
        self.resolver = EventResolver()
        
    def link_leg(self, leg_data: Dict, sport: str, date: str, description: str = None) -> Dict:
        """
        Attempts to link a leg to an event.
        Returns a dict with:
          - event_id: str (UUID) or None
          - selection_team_id: str (UUID) or None
          - link_status: 'LINKED' | 'QUARANTINED' | 'PENDING'
          - confidence: float
          - reason: str
        """
        candidates = self.resolver.find_candidates(leg_data, sport, date, description)
        
        if not candidates:
            return {
                "event_id": None,
                "selection_team_id": None,
                "link_status": "QUARANTINED",
                "confidence": 0.0,
                "reason": "No matching events found in window."
            }
            
        if len(candidates) == 1:
            match = candidates[0]
            # Simple policy: exact match is LINKED
            return {
                "event_id": match['event_id'],
                "selection_team_id": match.get('selection_team_id'),
                "link_status": "LINKED",
                "confidence": match['score'],
                "reason": match['reason']
            }
            
        # Ambiguous
        return {
            "event_id": None,
            "selection_team_id": None,
            "link_status": "QUARANTINED",
            "confidence": 0.0,
            "reason": f"Ambiguous: Found {len(candidates)} matches."
        }
