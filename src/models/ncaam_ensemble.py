"""
NCAAM Ensemble Model v2
Combines multiple data sources with weighted aggregation
"""

from typing import Dict, List, Optional
from src.models.ncaam_model import NCAAMModel
from src.services.espn_ncaa_client import ESPNNCAAClient
from src.services.season_stats_client import SeasonStatsClient
from src.models.injury_impact import get_injury_adjustment

class NCAAMEnsembleModel:
    """
    Ensemble model combining multiple prediction sources
    
    Weights:
    - BartTorvik: 30%
    - Existing Model: 22%
    - ESPN Injuries: 13%
    - Season Stats: 10%
    - Referee: 10%
    - Market Signals: 10%
    - KenPom: 5% (optional)
    """
    
    def __init__(self):
        self.base_model = NCAAMModel()
        self.espn_client = ESPNNCAAClient()
        self.season_stats = SeasonStatsClient()
        
        # Weights (must sum to 1.0)
        self.weights = {
            'barttorvik': 0.30,
            'base_model': 0.22,
            'espn_injury': 0.13,
            'season_stats': 0.10,
            'referee': 0.10,
            'market_signals': 0.10,
            'kenpom': 0.05  # Optional, redistribute if unavailable
        }
    
    def predict(self, home_team: str, away_team: str, game_id: str) -> Dict:
        """
        Generate ensemble prediction for a game
        
        Args:
            home_team: Home team name
            away_team: Away team name
            game_id: Game identifier
            
        Returns:
            Dict with ensemble spread, total, confidence, and source breakdown
        """
        # Collect adjustments from all sources
        adjustments = {
            'spread': {},
            'total': {}
        }
        
        # 1. Base Model (22% weight)
        # Already runs in find_edges, use its prediction as baseline
        adjustments['spread']['base_model'] = 0.0
        adjustments['total']['base_model'] = 0.0
        
        # 2. BartTorvik (30% weight)
        # Already integrated in base model via bt_team_metrics_daily
        adjustments['spread']['barttorvik'] = 0.0
        adjustments['total']['barttorvik'] = 0.0
        
        # 3. ESPN Injuries (13% weight)
        injury_adj = get_injury_adjustment(self.espn_client, home_team, away_team)
        adjustments['spread']['espn_injury'] = injury_adj.get('spread_adj', 0.0)
        adjustments['total']['espn_injury'] = injury_adj.get('total_adj', 0.0)
        
        # 4. Season Stats (10% weight)
        season_adj = self.season_stats.calculate_season_adjustment(home_team, away_team)
        adjustments['spread']['season_stats'] = season_adj.get('spread_adj', 0.0)
        adjustments['total']['season_stats'] = season_adj.get('total_adj', 0.0)
        
        # 5. Referee (10% weight) - TODO: implement
        adjustments['spread']['referee'] = 0.0
        adjustments['total']['referee'] = 0.0
        
        # 6. Market Signals (10% weight) - already in base model
        adjustments['spread']['market_signals'] = 0.0
        adjustments['total']['market_signals'] = 0.0
        
        # 7. KenPom (5% weight) - TODO: implement if subscription available
        adjustments['spread']['kenpom'] = 0.0
        adjustments['total']['kenpom'] = 0.0
        
        # Calculate weighted ensemble adjustments
        ensemble_spread_adj = self._weighted_sum(adjustments['spread'])
        ensemble_total_adj = self._weighted_sum(adjustments['total'])
        
        # Calculate confidence based on source agreement
        confidence = self._calculate_confidence(adjustments)
        
        return {
            'spread_adjustment': round(ensemble_spread_adj, 1),
            'total_adjustment': round(ensemble_total_adj, 1),
            'confidence': confidence,
            'sources': adjustments,
            'summary': self._generate_summary(adjustments, injury_adj, season_adj)
        }
    
    def _weighted_sum(self, source_values: Dict[str, float]) -> float:
        """
        Calculate weighted sum of source values
        
        Args:
            source_values: Dict of {source: value}
            
        Returns:
            Weighted sum
        """
        total = 0.0
        total_weight = 0.0
        
        for source, value in source_values.items():
            weight = self.weights.get(source, 0.0)
            total += weight * value
            total_weight += weight
        
        return total / total_weight if total_weight > 0 else 0.0
    
    def _calculate_confidence(self, adjustments: Dict) -> float:
        """
        Calculate confidence score based on source agreement
        
        Logic: If all sources agree on direction, confidence is high
        
        Returns:
            Confidence score 0.0 to 1.0
        """
        spread_values = [v for v in adjustments['spread'].values() if v != 0.0]
        
        if not spread_values:
            return 0.5  # Neutral
        
        # Check if all values have same sign (agreement)
        all_positive = all(v > 0 for v in spread_values)
        all_negative = all(v < 0 for v in spread_values)
        
        if all_positive or all_negative:
            return 0.85  # High confidence
        else:
            return 0.60  # Medium confidence (mixed signals)
    
    def _generate_summary(self, adjustments: Dict, injury_adj: Dict, season_adj: Dict) -> str:
        """Generate human-readable summary"""
        parts = []
        
        if injury_adj.get('injury_count', 0) > 0:
            parts.append(injury_adj.get('injury_summary', ''))
        
        if season_adj.get('summary'):
            parts.append(season_adj['summary'])
        
        return " | ".join(parts) if parts else "Standard prediction"


# Example usage
if __name__ == "__main__":
    model = NCAAMEnsembleModel()
    
    result = model.predict("Duke Blue Devils", "North Carolina Tar Heels", "game_123")
    
    print(f"Ensemble Adjustments:")
    print(f"  Spread: {result['spread_adjustment']:+.1f} pts")
    print(f"  Total: {result['total_adjustment']:+.1f} pts")
    print(f"  Confidence: {result['confidence']:.0%}")
    print(f"  Summary: {result['summary']}")
