import pytest
from unittest.mock import patch, MagicMock
from src.services.bracket_simulator import LiveBracketSimulator
from src.services.ncaam_tournament_service import NCAAMTournamentPredictionService

def test_production_playin_hotfix_split_and_simulate():
    """
    Simulates fetching DB rows where a play-in game is stored as a single slash-combined string.
    Ensures that LiveBracketSimulator.get_seeds_from_db splits it correctly,
    and that the resulting format is successfully processed by the canonical engine.
    """
    mock_db_rows = [
        {"region": "East", "seed": 1, "team_name": "Duke"},
        {"region": "East", "seed": 16, "team_name": "Howard / Wagner"},
        {"region": "East", "seed": 8, "team_name": "Kansas"},
        {"region": "East", "seed": 9, "team_name": "Kentucky"}
    ]

    # Mock the DB call
    with patch('src.services.bracket_simulator.get_db_connection'):
        with patch('src.services.bracket_simulator._exec') as mock_exec:
            mock_cursor = MagicMock()
            mock_cursor.fetchall.return_value = mock_db_rows
            mock_exec.return_value = mock_cursor
            
            simulator = LiveBracketSimulator(simulations=10)
            seeds_by_region = simulator.get_seeds_from_db()

    # Assert the split happened correctly
    assert "East" in seeds_by_region
    east_seeds = seeds_by_region["East"]
    
    # We started with 4 rows, but 1 was a play-in, so we should have 5 items now.
    assert len(east_seeds) == 5
    
    # Verify the play-in parsing
    seed_16_teams = [t["team_name"] for t in east_seeds if t["seed"] == 16]
    assert len(seed_16_teams) == 2
    assert "Howard" in seed_16_teams
    assert "Wagner" in seed_16_teams
    
    # Verify other teams are intact
    assert "Duke" in [t["team_name"] for t in east_seeds]
    assert "Howard / Wagner" not in [t["team_name"] for t in east_seeds]

    # Verify smooth simulation by mocking Torvik/KenPom to prevent live calls during test
    with patch('src.services.ncaam_tournament_service.NCAAMTournamentPredictionService.predict_game') as mock_predict:
        from src.services.ncaam_tournament_service import TournamentGamePrediction
        
        def side_effect(game_input):
            # Just mock a 50/50 tossup for the simulation to proceed without fetching live data for generic team names
            return TournamentGamePrediction(
                team_a=game_input.team_a, team_b=game_input.team_b,
                winner=game_input.team_a, winner_side="team_a",
                projected_spread_a=-2.0, projected_total=145.0,
                win_prob_a=55.0, win_prob_b=45.0, confidence_0_100=80.0
            )
        mock_predict.side_effect = side_effect
        
        service = NCAAMTournamentPredictionService()
        
        # We must construct a full 64 team field (4 regions x 16 seeds) so the MC loops don't break.
        # We will dynamically build it, injecting the split logic output into the East region.
        full_seeds = {"East": east_seeds, "West": [], "South": [], "Midwest": []}
        t_id_counter = 1
        for reg in ["West", "South", "Midwest"]:
            for s in range(1, 17):
                full_seeds[reg].append({"team_name": f"Team_{t_id_counter}", "seed": s, "region": reg})
                t_id_counter += 1
                
        # Fill out East so it has 16 seeds too (1, 8, 9, 16 are already there)
        for s in [2,3,4,5,6,7,10,11,12,13,14,15]:
            full_seeds["East"].append({"team_name": f"Team_{t_id_counter}", "seed": s, "region": "East"})
            t_id_counter += 1

        # This should execute successfully without raising SimulatorDataError or breaking
        res = service.simulate_bracket(full_seeds, simulations=10)
        
        assert hasattr(res, "first_four")
        assert len(res.first_four) > 0
        
        # Verify the First Four was evaluated (Howard vs Wagner)
        first_four_matchup = next((m for m in res.first_four if getattr(m, 'team_a') in ["Howard", "Wagner"]), None)
        assert first_four_matchup is not None
        assert getattr(first_four_matchup, 'team_a') == "Howard"
        assert getattr(first_four_matchup, 'team_b') == "Wagner"
