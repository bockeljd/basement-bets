import pytest
from unittest.mock import patch, MagicMock
from src.services.bracket_simulator import LiveBracketSimulator

def test_get_seeds_from_db_splits_slash_names():
    """
    Ensure rows with " / " in team_name are split into two separate seed entries.
    """
    simulator = LiveBracketSimulator()
    
    # Mock database rows
    mock_rows = [
        {'team_name': 'Duke', 'seed': 1, 'region': 'East'},
        {'team_name': 'Boise St. / Colorado', 'seed': 10, 'region': 'South'},
        {'team_name': 'Kansas', 'seed': 2, 'region': 'West'}
    ]
    
    with patch('src.services.bracket_simulator.get_db_connection') as mock_conn:
        with patch('src.services.bracket_simulator._exec') as mock_exec:
            mock_exec.return_value.fetchall.return_value = mock_rows
            
            seeds = simulator.get_seeds_from_db()
            
    # Check East
    assert len(seeds['East']) == 1
    assert seeds['East'][0]['team_name'] == 'Duke'
    
    # Check South (should have 2 teams now)
    assert len(seeds['South']) == 2
    assert seeds['South'][0]['team_name'] == 'Boise St.'
    assert seeds['South'][1]['team_name'] == 'Colorado'
    assert seeds['South'][0]['seed'] == 10
    assert seeds['South'][1]['seed'] == 10
    
    # Check overall count
    total_teams = sum(len(lst) for lst in seeds.values())
    assert total_teams == 4
