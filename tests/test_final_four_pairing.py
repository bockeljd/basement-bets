import pytest
from unittest.mock import MagicMock, patch
from src.services.ncaam_tournament_service import NCAAMTournamentPredictionService
from src.services.ncaam_bracket_state_service import NCAAMBracketStateService, FINAL_FOUR_PAIRS

def test_final_four_pairs_constant():
    # Verify the constant in bracket_state_service
    expected = [
        ({"East", "South"}, 0),
        ({"West", "Midwest"}, 1)
    ]
    assert FINAL_FOUR_PAIRS == expected

@patch("src.database.get_db_connection")
@patch.object(NCAAMTournamentPredictionService, "preheat_cache")
@patch.object(NCAAMTournamentPredictionService, "predict_game")
def test_simulate_bracket_final_four_pairing(mock_predict, mock_preheat, mock_db):
    service = NCAAMTournamentPredictionService()
    
    
    # Provide 16 teams per region to ensure E8 winners are generated
    seeds = {}
    for region in ["East", "West", "South", "Midwest"]:
        seeds[region] = []
        for i in range(1, 17):
            seeds[region].append({"seed": i, "team_name": f"{region}Team{i}"})

    from src.services.ncaam_tournament_service import TournamentGamePrediction
    
    # We also need to map the predicted winners correctly in side_effect
    def side_effect(game_input, conn=None):
        return TournamentGamePrediction(
            team_a=game_input.team_a, 
            team_b=game_input.team_b,
            winner=game_input.team_a, 
            winner_side="team_a",
            projected_spread_a=-5.0,
            projected_total=145.0,
            win_prob_a=60.0, 
            win_prob_b=40.0,
            confidence_0_100=80.0,
            model_type="tournament_ensemble_v1",
            neutral_site=True,
            market_data_used=False,
            fallback_used=False,
            reason_codes=[],
            risk_flags=[],
            debug={}
        )
    
    mock_predict.side_effect = side_effect
    
    # Run simulation with 1 iteration for speed
    result = service.simulate_bracket(seeds, simulations=1)
    
    # 1. Check Deterministic path
    ff_det = result.final_four
    assert len(ff_det) == 2
    # Match 0: East vs South
    teams_0 = {ff_det[0].team_a, ff_det[0].team_b}
    assert any(t.startswith("East") for t in teams_0)
    assert any(t.startswith("South") for t in teams_0)
    
    # Match 1: West vs Midwest
    teams_1 = {ff_det[1].team_a, ff_det[1].team_b}
    assert any(t.startswith("West") for t in teams_1)
    assert any(t.startswith("Midwest") for t in teams_1)
    
    # 2. Check Most-likely path
    ml = result.most_likely_bracket
    ff_ml = ml["final_four"]
    assert len(ff_ml) == 2
    ml_teams_0 = {ff_ml[0]["team_a"], ff_ml[0]["team_b"]}
    assert any(t.startswith("East") for t in ml_teams_0)
    assert any(t.startswith("South") for t in ml_teams_0)

    ml_teams_1 = {ff_ml[1]["team_a"], ff_ml[1]["team_b"]}
    assert any(t.startswith("West") for t in ml_teams_1)
    assert any(t.startswith("Midwest") for t in ml_teams_1)

@patch.object(NCAAMBracketStateService, "_load_seed_rows")
@patch.object(NCAAMBracketStateService, "_fetch_actual_events")
def test_bracket_state_assign_final_four_slot(mock_fetch, mock_load):
    service = NCAAMBracketStateService()
    
    # Test East/South -> Slot 0
    slot_0 = service._assign_final_four_slot(("East", "South"))
    assert slot_0 == 0
    
    # Test West/Midwest -> Slot 1
    slot_1 = service._assign_final_four_slot(("West", "Midwest"))
    assert slot_1 == 1
    
    # Test invalid pairing
    assert service._assign_final_four_slot(("East", "West")) is None
    assert service._assign_final_four_slot(("South", "Midwest")) is None
