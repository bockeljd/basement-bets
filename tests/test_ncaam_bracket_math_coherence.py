import pytest
from unittest.mock import patch, MagicMock
from src.services.ncaam_tournament_service import NCAAMTournamentPredictionService
from src.services.bracket_simulator import LiveBracketSimulator

@pytest.fixture
def mock_seeds():
    # To test championship probabilities, the simulator requires a full 64-team field 
    # (16 seeds in 4 regions) because its loop logic expects all 8 standard matchups per region.
    regions = ["East", "West", "South", "Midwest"]
    bracket = {}
    team_id = 1
    
    for r in regions:
        bracket[r] = []
        for seed in range(1, 17):
            bracket[r].append({
                "team_name": f"Team_{team_id}",
                "seed": seed
            })
            team_id += 1
            
    return bracket

@pytest.fixture
def mock_torvik_kenpom():
    with patch("src.models.ncaam_market_first_model_v2.TorvikProjectionService") as MockTorvik, \
         patch("src.models.ncaam_market_first_model_v2.KenPomClient") as MockKenpom:
         
        mock_torvik = MockTorvik.return_value
        mock_torvik.get_projection.return_value = {
            "margin": 5.0,
            "total": 145.0,
            "lean": "Duke"
        }
        mock_torvik.get_matchup_team_stats.return_value = {
            "game_tempo": 68.0,
            "home": {"luck": 0.0, "continuity": 70.0},
            "away": {"luck": 0.0, "continuity": 70.0}
        }
        
        mock_kenpom = MockKenpom.return_value
        mock_kenpom.calculate_kenpom_adjustment.return_value = {
            "spread_adj": -5.0,
            "total_adj": 0.0
        }
        mock_kenpom.get_team_player_agg.return_value = {"ortg_w": 105.0}
        
        yield

def test_prob_monotonicity_by_round(mock_seeds, mock_torvik_kenpom):
    """
    Ensure the simulated advancement percentages always decrease
    or stay the same round-over-round. (You can't have a higher chance
    of making the Elite 8 than you do making the Sweet 16).
    """
    service = NCAAMTournamentPredictionService()
    # 100 simulations is enough to give valid float math bounds.
    res = service.simulate_bracket(mock_seeds, simulations=100)
    
    probs = res.round_advancement_probs
    
    for p in probs:
        team = p.team_name
        assert p.r32_prob >= p.s16_prob, f"{team} S16 prob ({p.s16_prob}%) > R32 prob ({p.r32_prob}%)"
        assert p.s16_prob >= p.e8_prob, f"{team} E8 prob ({p.e8_prob}%) > S16 prob ({p.s16_prob}%)"
        assert p.e8_prob >= p.final_four_prob, f"{team} FF prob ({p.final_four_prob}%) > E8 prob ({p.e8_prob}%)"
        assert p.final_four_prob >= p.championship_prob, f"{team} NCG prob ({p.championship_prob}%) > FF prob ({p.final_four_prob}%)"
        assert p.championship_prob >= p.champion_prob, f"{team} Champ prob ({p.champion_prob}%) > NCG prob ({p.championship_prob}%)"

def test_title_odds_sum_to_one(mock_seeds, mock_torvik_kenpom):
    """
    Ensure the sum of all championship win probabilities across the field
    equals 100% (or very close to it given float rounding).
    """
    service = NCAAMTournamentPredictionService()
    res = service.simulate_bracket(mock_seeds, simulations=100)
    
    probs = res.round_advancement_probs
    total_champ_prob = sum(p.champion_prob for p in probs)
    
    # Should sum to 100.0%
    assert 99.0 <= total_champ_prob <= 101.0, f"Total championship prob is {total_champ_prob}%"
