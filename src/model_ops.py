"""
Model Operations Module
Handles Model Registry, Versioning, and Prediction Storage.
"""

import json
from datetime import datetime
from typing import Dict, Any, Optional
import os
import sys

# Adjust imports based on project structure
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.database import register_model_version, store_prediction_v2

class ModelRegistry:
    
    def __init__(self):
        pass

    def register_version(self, sport: str, tag: str, config: Dict, lifecycle: str = 'experimental') -> int:
        """
        Register a new model version.
        Returns the new version ID.
        """
        print(f"[ModelRegistry] Registering {sport} model {tag} ({lifecycle})...")
        version_id = register_model_version(sport, tag, config, lifecycle)
        print(f"[ModelRegistry] Registered ID: {version_id}")
        return version_id

    def log_prediction(self, 
                       version_id: int, 
                       event_id: str, 
                       league: str, 
                       market: str, 
                       snapshot_date: datetime,
                       outputs: Dict[str, float]):
        """
        Log a probabilistic prediction with strict snapshot timing.
        
        outputs expected keys:
        - win_prob
        - cover_prob
        - over_prob
        - implied_margin
        - implied_total
        - uncertainty
        """
        
        # Prepare data packet for DB
        data = {
            "model_version_id": version_id,
            "event_id": event_id,
            "league": league,
            "market_type": market,
            "feature_snapshot_date": snapshot_date,
            "win_prob": outputs.get("win_prob"),
            "cover_prob": outputs.get("cover_prob"),
            "over_prob": outputs.get("over_prob"),
            "implied_margin": outputs.get("implied_margin"),
            "implied_total": outputs.get("implied_total"),
            "uncertainty": outputs.get("uncertainty")
        }
        
        # Store
        pred_id = store_prediction_v2(data)
        return pred_id

if __name__ == "__main__":
    # Smoke Test
    reg = ModelRegistry()
    vid = reg.register_version("NFL", "v1.0.0-smoke", {"features": ["elo", "rest"]}, "experimental")
    
    reg.log_prediction(
        vid, 
        "test-event-uuid", 
        "NFL", 
        "spread", 
        datetime.now(), 
        {"win_prob": 0.55, "implied_margin": 3.5}
    )
