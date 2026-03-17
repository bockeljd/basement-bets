import pytest
from unittest.mock import patch, MagicMock
from src.services.ncaam_tournament_service import (
    NCAAMTournamentPredictionService, 
    TournamentGameInput,
    SimulatorDataError
)

@pytest.fixture
def mock_analyze():
    with patch("src.models.ncaam_market_first_model_v2.NCAAMMarketFirstModelV2.analyze_tournament_game") as mock:
        yield mock

def test_predict_game_maps_results_correctly(mock_analyze):
    service = NCAAMTournamentPredictionService()
    
    # Mock return from analyze_tournament_game
    mock_analyze.return_value = {
        "team_a": "Duke",
        "team_b": "North Carolina",
        "winner": "Duke",
        "winner_side": "team_a",
        "projected_spread_a": -4.5,
        "projected_total": 145.5,
        "win_prob_a": 65.0,
        "win_prob_b": 35.0,
        "confidence_0_100": 70.0,
        "market_data_used": False,
        "fallback_used": False,
        "reason_codes": ["Duke has better AdjEM", "UNC fatigue modifier applied"],
        "risk_flags": ["High pace variance"],
        "debug": {}
    }
    
    res = service.predict_game(TournamentGameInput(
        team_a="Duke", 
        team_b="North Carolina", 
        round_index=1,
        neutral_site=True
    ))
    
    assert res.team_a == "Duke"
    assert res.winner == "Duke"
    assert res.projected_spread_a == -4.5
    assert res.win_prob_a == 65.0
    assert "UNC fatigue modifier applied" in res.reason_codes
    assert mock_analyze.call_count == 1

def test_simulate_bracket_playin_resolution(mock_analyze):
    # Mocking predictable outcomes
    def mock_predict(*args, **kwargs):
        team_a = kwargs.get("team_a")
        team_b = kwargs.get("team_b")
        
        # Make the alphabetically first team win
        winner = min(team_a, team_b)
        
        return {
            "team_a": team_a,
            "team_b": team_b,
            "winner": winner,
            "winner_side": "team_a" if winner == team_a else "team_b",
            "projected_spread_a": -2.0 if winner == team_a else 2.0,
            "projected_total": 140.0,
            "win_prob_a": 55.0 if winner == team_a else 45.0,
            "win_prob_b": 45.0 if winner == team_a else 55.0,
            "confidence_0_100": 60.0,
            "market_data_used": False,
            "fallback_used": False,
            "reason_codes": [],
            "risk_flags": [],
        }
        
    mock_analyze.side_effect = mock_predict
    
    service = NCAAMTournamentPredictionService()
    
    # Setup mock bracket with play-in
    seeds = {
        "East": [
            {"team_name": "UConn", "seed": 1},
            {"team_name": "Stetson", "seed": 16},
            {"team_name": "Iowa State", "seed": 2},
            {"team_name": "South Dakota State", "seed": 15},
            {"team_name": "Illinois", "seed": 3},
            {"team_name": "Morehead State", "seed": 14},
            {"team_name": "Auburn", "seed": 4},
            {"team_name": "Yale", "seed": 13},
            {"team_name": "San Diego State", "seed": 5},
            {"team_name": "UAB", "seed": 12},
            {"team_name": "BYU", "seed": 6},
            {"team_name": "Duquesne", "seed": 11},
            {"team_name": "Washington State", "seed": 7},
            {"team_name": "Drake", "seed": 10},
            {"team_name": "Florida Atlantic", "seed": 8},
            {"team_name": "Northwestern", "seed": 9},
        ],
        "South": [
            {"team_name": "Houston", "seed": 1},
            {"team_name": "Longwood", "seed": 16},
            {"team_name": "Marquette", "seed": 2},
            {"team_name": "Western Kentucky", "seed": 15},
            {"team_name": "Kentucky", "seed": 3},
            {"team_name": "Oakland", "seed": 14},
            {"team_name": "Duke", "seed": 4},
            {"team_name": "Vermont", "seed": 13},
            {"team_name": "Wisconsin", "seed": 5},
            {"team_name": "James Madison", "seed": 12},
            {"team_name": "Texas Tech", "seed": 6},
            {"team_name": "NC State", "seed": 11},
            {"team_name": "Florida", "seed": 7},
            # PLAY IN EXAMPLE: Multiple entries for seed 10
            {"team_name": "Boise State", "seed": 10},
            {"team_name": "Colorado", "seed": 10},
            {"team_name": "Nebraska", "seed": 8},
            {"team_name": "Texas A&M", "seed": 9},
        ]
    }
    
    # Needs to be flat 64 (or 68 if play in), let's just test single region properly
    res = service.simulate_bracket(seeds, simulations=10)
    
    assert res.season == "2025-26"
    assert "East" in res.regions
    assert "South" in res.regions
    
    # Play-in games are caught
    assert len(res.first_four) > 0
    assert any("Colorado" in gm.team_a or "Colorado" in gm.team_b for gm in res.first_four)
    
    # Deterministic bracket populated
    assert res.regions["South"]["round_of_64"]
    assert len(res.regions["South"]["round_of_32"]) > 0
