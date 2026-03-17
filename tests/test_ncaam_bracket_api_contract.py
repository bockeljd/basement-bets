import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from src.api import app

client = TestClient(app)

@pytest.fixture
def mock_sim_cache():
    with patch("src.api_extensions.ncaam_bracket_api._SIM_CACHE", {}) as mock:
        yield mock

@pytest.fixture
def mock_service():
    with patch("src.services.ncaam_tournament_service.NCAAMTournamentPredictionService") as mock:
        yield mock

@pytest.fixture
def mock_simulator():
    with patch("src.api_extensions.ncaam_bracket_api.LiveBracketSimulator") as mock:
        yield mock

def test_bracket_api_contract(mock_service, mock_simulator, mock_sim_cache):
    # Setup mock dependencies
    mock_sim_inst = mock_simulator.return_value
    mock_sim_inst.get_seeds_from_db.return_value = {
        "East": [
            {"team_name": "UConn", "seed": 1},
            {"team_name": "Stetson", "seed": 16}
        ]
    }
    
    mock_service_inst = mock_service.return_value
    mock_sim_obj = MagicMock()
    
    # Mock model_dump output
    mock_sim_obj.model_dump.return_value = {
        "season": "2025-26",
        "regions": {
            "East": {
                "round_of_64": [
                    {
                        "team_a": "UConn",
                        "team_b": "Stetson",
                        "winner": "UConn",
                        "projected_spread_a": -25.0,
                        "projected_total": 145.0,
                        "win_prob_a": 99.0,
                        "win_prob_b": 1.0,
                        "confidence_0_100": 80.0
                    }
                ]
            }
        },
        "first_four": [],
        "final_four": [],
        "championship": None,
        "round_advancement_probs": []
    }
    mock_service_inst.simulate_bracket.return_value = mock_sim_obj
    
    # Override access key dependency so we don't get 403
    with patch("src.api.settings.BASEMENT_PASSWORD", "test"):
        res = client.get("/api/ncaam/bracket/2026?refresh=true", headers={"X-BASEMENT-KEY": "test"})
    
    assert res.status_code == 200
    
    data = res.json()
    assert data["season"] == "2025-26"
    assert data["v"] == "5-canonical"
    
    # Check that seeds were injected correctly!
    r64_game = data["regions"]["East"]["round_of_64"][0]
    assert r64_game["seed_a"] == 1
    assert r64_game["seed_b"] == 16
    
    # Check that seeds wrapper exists on region
    assert len(data["regions"]["East"]["seeds"]) == 2
