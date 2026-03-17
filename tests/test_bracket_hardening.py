import pytest
from unittest.mock import patch, MagicMock
from src.services.ncaam_tournament_service import (
    NCAAMTournamentPredictionService, 
    TournamentGameInput,
    SimulatorDataError
)

def test_seed_based_fallback_probability():
    """
    Test that the fallback logic uses seed-based priors.
    1-seed vs 16-seed should NOT be 50/50.
    """
    service = NCAAMTournamentPredictionService()
    
    seeds = {
        "East": [
            {"team_name": "UConn", "seed": 1},
            {"team_name": "NonExistentTeam", "seed": 16},
        ],
        "South": [], "West": [], "Midwest": []
    }
    
    # Mock predict_game to raise an error for the unknown team
    with patch.object(service, 'predict_game') as mock_predict:
        mock_predict.side_effect = Exception("Missing metrics")
        
        # We only need 1 simulation to check the logic
        res = service.simulate_bracket(seeds, simulations=1)
        
    assert res.degraded_simulation is True
    assert len(res.data_issues) > 0
    
    # Check the deterministic matchup in R64
    r64_matchup = res.regions["East"]["round_of_64"][0]
    assert r64_matchup.fallback_used is True
    # 0.5 + (16-1)*0.04 = 0.5 + 0.6 = 1.1 -> clamped to 0.95 -> 95.0%
    assert r64_matchup.win_prob_a == 95.0
    assert "Seed-based fallback prior" in r64_matchup.reason_codes[0]

def test_degraded_simulation_propagation():
    """
    Verify that if ANY game triggers a fallback, the top-level flag is true.
    """
    service = NCAAMTournamentPredictionService()
    
    seeds = {
        "East": [
            {"team_name": "Duke", "seed": 1},
            {"team_name": "UNC", "seed": 16},
        ],
        "South": [], "West": [], "Midwest": []
    }
    
    # Mock one game to fail
    with patch.object(service, 'predict_game') as mock_predict:
        # First call (Duke vs UNC) fails
        mock_predict.side_effect = [Exception("Oops"), MagicMock()]
        
        res = service.simulate_bracket(seeds, simulations=1)
        
    assert res.degraded_simulation is True
    assert any(gm.fallback_used for gm in res.regions["East"]["round_of_64"])
