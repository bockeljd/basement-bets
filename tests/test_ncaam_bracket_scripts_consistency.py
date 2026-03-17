import pytest
from unittest.mock import patch, MagicMock
from src.services.bracket_simulator import LiveBracketSimulator
from src.services.ncaam_tournament_service import TournamentBracketSimulation, TournamentGamePrediction

@pytest.fixture
def mock_service():
    with patch("src.services.ncaam_tournament_service.NCAAMTournamentPredictionService") as mock:
        yield mock

def test_live_bracket_simulator_delegates_single_game(mock_service):
    # Setup mock
    service_instance = mock_service.return_value
    service_instance.predict_game.return_value = TournamentGamePrediction(
        team_a="Purdue",
        team_b="Grambling State",
        winner="Purdue",
        winner_side="team_a",
        projected_spread_a=-24.5,
        projected_total=135.0,
        win_prob_a=98.0,
        win_prob_b=2.0,
        confidence_0_100=80.0,
        market_data_used=False,
        fallback_used=False,
        reason_codes=["Huge mismatch"],
        risk_flags=["Blowout potential"]
    )
    
    wrapper = LiveBracketSimulator()
    res = wrapper.simulate_game("Purdue", "Grambling State", 0)
    
    # Assert wrapper formats to old expected struct
    assert res["team_a"] == "Purdue"
    assert res["team_b"] == "Grambling State"
    assert res["spread"] == -24.5
    assert res["total"] == 135.0
    assert res["win_prob_a"] == 98.0
    assert res["winner"] == "Purdue"
    assert "Canonical" in res["summary"]
    
def test_live_bracket_simulator_dumps_full_model(mock_service):
    # Setup mock full model
    service_instance = mock_service.return_value
    mock_sim = TournamentBracketSimulation(
        season="2025-26",
        simulated_at="now",
        model_version="test",
        regions={"East": {"round_of_64": []}},
        first_four=[],
        final_four=[],
        round_advancement_probs=[]
    )
    service_instance.simulate_bracket.return_value = mock_sim
    
    wrapper = LiveBracketSimulator(simulations=10)
    res = wrapper.simulate_full_bracket({})
    
    # Must be a raw dict matching the Pydantic dump
    assert type(res) == dict
    assert res["season"] == "2025-26"
    assert res["model_version"] == "test"
    assert "East" in res["regions"]
