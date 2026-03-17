import pytest
from unittest.mock import patch, MagicMock
from src.services.ncaam_tournament_features import NCAAMTournamentFeatures

@pytest.fixture
def mock_db_connection():
    with patch("src.database.get_db_connection") as mock_conn:
        with patch("src.database._exec") as mock_exec:
            yield mock_conn, mock_exec

def test_get_team_tournament_profile(mock_db_connection):
    mock_conn, mock_exec = mock_db_connection
    
    # Mocking _exec fetchone
    mock_cursor = MagicMock()
    mock_cursor.fetchone.side_effect = [
        {"team_name": "Duke", "rank": 10, "adj_em": 20.0}, # Kenpom
        {"team_name": "Duke", "net_rank": 5, "quad1": "6-2"}, # NET
        {"adj_tempo": 65.0, "luck": 0.05, "continuity": 60.0, "torvik_rank": 8}, # Torvik daily
        {"barthag": 0.95, "rank": 8, "adj_o": 120.0, "adj_d": 90.0} # Torvik ratings
    ]
    mock_exec.return_value = mock_cursor

    features = NCAAMTournamentFeatures()
    features.matcher = MagicMock()
    features.matcher.find_source_name.return_value = "Duke"
    
    features.kp_client = MagicMock()
    features.kp_client.get_player_stats_for_team.return_value = [{"player_name": "Player 1", "metrics": {"min": 35.0, "pts": 20.0}}]
    features.kp_client.get_team_player_agg.return_value = {"top7_minutes_pct": 89.0, "tov_rate_w": 21.0}
    
    profile = features.get_team_tournament_profile("Duke")
    
    assert profile["team_name"] == "Duke"
    assert profile["kenpom"]["adj_em"] == 20.0
    assert profile["luck"] == 0.05
    assert profile["continuity"] == 60.0
    assert profile["q1_wins"] == 6

def test_get_tournament_modifiers(mock_db_connection):
    mock_conn, mock_exec = mock_db_connection
    
    mock_cursor = MagicMock()
    mock_cursor.fetchone.side_effect = [
        {"team_name": "Duke", "rank": 10, "adj_em": 20.0}, # Kenpom
        {"team_name": "Duke", "net_rank": 5, "quad1": "6-2"}, # NET
        {"adj_tempo": 65.0, "luck": 0.05, "continuity": 80.0, "torvik_rank": 8}, # Torvik daily
        {"barthag": 0.95, "rank": 8, "adj_o": 120.0, "adj_d": 90.0} # Torvik ratings
    ]
    mock_exec.return_value = mock_cursor

    features = NCAAMTournamentFeatures()
    features.matcher = MagicMock()
    features.matcher.find_source_name.return_value = "Duke"
    
    # We patch kp_client directly to return our mocks
    features.kp_client.get_player_stats_for_team = MagicMock(return_value=[])
    features.kp_client.get_team_player_agg = MagicMock(return_value={"top7_minutes_pct": 89.0, "tov_rate_w": 21.0})
    
    mods = features.get_tournament_modifiers("Duke")
    
    assert mods["luck_adj_points"] == -1.5 # luck > 0.04
    assert mods["continuity_adj_points"] == 0.5 # cont > 75
    assert mods["turnover_adj_points"] == -1.0 # tov > 20
    assert mods["q1_adj_points"] == 1.0 # q1 >= 6
    assert mods["variance_multiplier"] == 1.15 # top7 > 85

def test_missing_team_fallback(mock_db_connection):
    mock_conn, mock_exec = mock_db_connection
    
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = None # Nothing found in DB
    mock_exec.return_value = mock_cursor

    features = NCAAMTournamentFeatures()
    features.kp_client.get_player_stats_for_team = MagicMock(return_value=[])
    features.kp_client.get_team_player_agg = MagicMock(return_value={})
    
    profile = features.get_team_tournament_profile("Unknown Team")
    
    assert profile["team_name"] == "Unknown Team"
    assert profile["luck"] == 0.0
    assert profile["continuity"] == 0.0
    
    # Modifiers should just be baseline 1.0
    mods = features.get_tournament_modifiers("Unknown Team")
    assert mods["variance_multiplier"] == 1.0
    assert mods["luck_adj_points"] == 0.0
