import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.services.ncaam_bracket_state_service import NCAAMBracketStateService


@pytest.fixture
def base_payload():
    return {
        "season": "2025-26",
        "regions": {
            "East": {
                "round_of_64": [
                    {
                        "team_a": "Duke Blue Devils",
                        "team_b": "Siena Saints",
                        "winner": "Siena Saints",
                        "win_prob_a": 80.0,
                        "win_prob_b": 20.0,
                        "debug": {"model": "tournament_ensemble_v1"},
                        "model_type": "tournament_ensemble_v1"
                    }
                ]
            }
        },
        "first_four": [],
        "final_four": [],
        "championship": None,
        "title_odds": {"Duke Blue Devils": 28.7},
        "round_advancement_probs": []
    }


def _seed_rows():
    return [
        {"team_name": "Duke Blue Devils", "seed": 1, "region": "East"},
        {"team_name": "Siena Saints", "seed": 16, "region": "East"}
    ]


def _final_event():
    return [{
        "home_team": "Duke Blue Devils",
        "away_team": "Siena Saints",
        "start_time": datetime.utcnow(),
        "status": "final",
        "final": True,
        "home_score": 78,
        "away_score": 71
    }]


def _live_event():
    return [{
        "home_team": "Duke Blue Devils",
        "away_team": "Siena Saints",
        "start_time": datetime.utcnow(),
        "status": "IN_PROGRESS",
        "final": False,
        "home_score": 42,
        "away_score": 41
    }]


@patch("src.services.ncaam_bracket_state_service.NCAAMTournamentPredictionService")
@patch.object(NCAAMBracketStateService, "_fetch_actual_events")
@patch.object(NCAAMBracketStateService, "_load_seed_rows")
def test_final_results_override_projection(mock_load, mock_fetch, mock_service, base_payload):
    mock_load.return_value = _seed_rows()
    mock_fetch.return_value = _final_event()

    mock_sim = MagicMock()
    mock_sim.model_dump.return_value = base_payload.copy()
    mock_service.return_value.simulate_bracket.return_value = mock_sim

    service = NCAAMBracketStateService()
    result = service.build_bracket_payload()

    match = result["regions"]["East"]["round_of_64"][0]
    assert match["status"] == "final"
    assert match["display_winner"] == "Duke Blue Devils"
    assert match["winner_source"] == "final"
    assert match["actual_score_a"] == 78
    assert result["seed_metadata"]["source"] == "manual_bracket_data"

    locked = mock_service.return_value.simulate_bracket.call_args[1]["locked_matchups"]
    assert locked
    assert locked[0]["winner"] == "Duke Blue Devils"


@patch("src.services.ncaam_bracket_state_service.NCAAMTournamentPredictionService")
@patch.object(NCAAMBracketStateService, "_fetch_actual_events")
@patch.object(NCAAMBracketStateService, "_load_seed_rows")
def test_live_status_overrides_projection(mock_load, mock_fetch, mock_service, base_payload):
    mock_load.return_value = _seed_rows()
    mock_fetch.return_value = _live_event()

    mock_sim = MagicMock()
    mock_sim.model_dump.return_value = base_payload.copy()
    mock_service.return_value.simulate_bracket.return_value = mock_sim

    service = NCAAMBracketStateService()
    result = service.build_bracket_payload()

    match = result["regions"]["East"]["round_of_64"][0]
    assert match["status"] == "live"
    assert match["winner_source"] == "live"
    assert match["actual_score_a"] == 42
    assert match["actual_score_b"] == 41

    locked = mock_service.return_value.simulate_bracket.call_args[1]["locked_matchups"]
    assert not locked
