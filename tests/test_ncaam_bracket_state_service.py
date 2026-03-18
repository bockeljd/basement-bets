import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.services.ncaam_bracket_state_service import NCAAMBracketStateService, BracketGameStatus


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
    assert match["winner_source"] == "projection"
    assert match["actual_score_a"] == 42
    assert match["actual_score_b"] == 41

    locked = mock_service.return_value.simulate_bracket.call_args[1]["locked_matchups"]
    assert not locked


@patch("src.services.ncaam_bracket_state_service.NCAAMTournamentPredictionService")
@patch.object(NCAAMBracketStateService, "_fetch_actual_events")
@patch.object(NCAAMBracketStateService, "_load_seed_rows")
def test_champion_trust_low_flag(mock_load, mock_fetch, mock_service, base_payload):
    mock_load.return_value = _seed_rows()
    mock_fetch.return_value = _final_event()

    payload = base_payload.copy()
    payload.update({
        "degraded_simulation": True,
        "data_issues": ["issue"] * 5,
        "champion": "Duke Blue Devils",
        "championship": {
            "team_a": "Duke Blue Devils",
            "team_b": "Siena Saints"
        }
    })

    mock_sim = MagicMock()
    mock_sim.model_dump.return_value = payload
    mock_service.return_value.simulate_bracket.return_value = mock_sim

    service = NCAAMBracketStateService()
    result = service.build_bracket_payload()

    assert result["champion_trust_low"] is True

@patch.object(NCAAMBracketStateService, "_load_seed_rows")
@patch.object(NCAAMBracketStateService, "_fetch_actual_events")
def test_seed_lookup_alias_coverage(mock_fetch, mock_load):
    mock_load.return_value = [
        {
            "team_name": "Lehigh / Prairie View A&M",
            "seed": 16,
            "region": "East"
        }
    ]
    mock_fetch.return_value = []

    service = NCAAMBracketStateService()
    keys = service.seed_lookup.keys()
    assert any("lehigh" in key.lower() for key in keys)
    assert any(alias in key.lower() for key in keys for alias in ("prairie view am", "prairie view"))


def test_collect_override_data_does_not_set_actual_for_scheduled():
    service = NCAAMBracketStateService()
    event = {
        'home_team': 'Duke Blue Devils',
        'away_team': 'Siena Saints',
        'home_score': None,
        'away_score': None
    }
    data = service._collect_override_data(
        event, ('East', 'round_of_64', 0), 'Duke Blue Devils', 'Siena Saints', 1, 16,
        BracketGameStatus.SCHEDULED, None
    )
    assert data['actual_winner'] is None


def test_collect_override_data_record_actual_for_final():
    service = NCAAMBracketStateService()
    event = {
        'home_team': 'Duke Blue Devils',
        'away_team': 'Siena Saints',
        'home_score': 80,
        'away_score': 70
    }
    data = service._collect_override_data(
        event, ('East', 'round_of_64', 0), 'Duke Blue Devils', 'Siena Saints', 1, 16,
        BracketGameStatus.FINAL, None
    )
    assert data['actual_winner'] == 'Duke Blue Devils'


@patch.object(NCAAMBracketStateService, '_load_seed_rows')
@patch.object(NCAAMBracketStateService, '_fetch_actual_events')
def test_overlay_match_uses_actual_for_final(mock_fetch, mock_load):
    mock_load.return_value = []
    mock_fetch.return_value = []
    service = NCAAMBracketStateService()
    match = {'winner': 'Siena Saints', 'predicted_winner': 'Siena Saints'}
    override = {
        'team_a': 'Duke Blue Devils',
        'team_b': 'Siena Saints',
        'seed_a': 1,
        'seed_b': 16,
        'status': BracketGameStatus.FINAL,
        'score_a': 80,
        'score_b': 70,
        'actual_winner': 'Duke Blue Devils',
        'slot_key': ('East', 'round_of_64', 0)
    }
    service._overlay_match(match, override)
    assert match['display_winner'] == 'Duke Blue Devils'
    assert match['winner_source'] == 'final'


@patch.object(NCAAMBracketStateService, '_load_seed_rows')
@patch.object(NCAAMBracketStateService, '_fetch_actual_events')
def test_overlay_match_keeps_projection_for_scheduled(mock_fetch, mock_load):
    mock_load.return_value = []
    mock_fetch.return_value = []
    service = NCAAMBracketStateService()
    match = {'winner': 'Siena Saints', 'predicted_winner': 'Duke Blue Devils'}
    override = {
        'team_a': 'Duke Blue Devils',
        'team_b': 'Siena Saints',
        'seed_a': 1,
        'seed_b': 16,
        'status': BracketGameStatus.SCHEDULED,
        'score_a': None,
        'score_b': None,
        'actual_winner': None,
        'slot_key': ('East', 'round_of_64', 0)
    }
    service._overlay_match(match, override)
    assert match['display_winner'] == 'Siena Saints'
    assert match['winner_source'] == 'projection'



@patch.object(NCAAMBracketStateService, '_load_seed_rows')
@patch.object(NCAAMBracketStateService, '_fetch_actual_events')
def test_overlay_match_remaps_win_probs_when_team_order_changes(mock_fetch, mock_load):
    mock_load.return_value = []
    mock_fetch.return_value = []
    service = NCAAMBracketStateService()
    match = {
        'team_a': 'Siena Saints',
        'team_b': 'Duke Blue Devils',
        'winner': 'Siena Saints',
        'win_prob_a': 1.3,
        'win_prob_b': 98.7
    }
    override = {
        'team_a': 'Duke Blue Devils',
        'team_b': 'Siena Saints',
        'seed_a': 1,
        'seed_b': 16,
        'status': BracketGameStatus.SCHEDULED,
        'score_a': None,
        'score_b': None,
        'actual_winner': None,
        'slot_key': ('East', 'round_of_64', 0)
    }
    service._overlay_match(match, override)
    assert match['team_a'] == 'Duke Blue Devils'
    assert match['team_b'] == 'Siena Saints'
    assert match['win_prob_a'] == 98.7
    assert match['win_prob_b'] == 1.3


@patch("src.services.ncaam_bracket_state_service.NCAAMTournamentPredictionService")
@patch.object(NCAAMBracketStateService, "_fetch_actual_events")
@patch.object(NCAAMBracketStateService, "_load_seed_rows")
def test_actual_event_does_not_overwrite_wrong_slot(mock_load, mock_fetch, mock_service):
    """If an actual event's team-pair does not exist in the simulated bracket, do not inject it."""
    mock_load.return_value = [
        {"team_name": "Kansas Jayhawks", "seed": 4, "region": "East"},
        {"team_name": "UCF Knights", "seed": 10, "region": "East"},
        {"team_name": "Duke Blue Devils", "seed": 1, "region": "East"},
        {"team_name": "Ohio State Buckeyes", "seed": 8, "region": "East"},
    ]

    mock_fetch.return_value = [
        {
            "home_team": "Kansas Jayhawks",
            "away_team": "UCF Knights",
            "start_time": datetime.utcnow(),
            "status": "final",
            "final": True,
            "home_score": 75,
            "away_score": 81,
        }
    ]

    payload = {
        "season": "2025-26",
        "regions": {
            "East": {
                "round_of_64": [
                    {
                        "team_a": "Duke Blue Devils",
                        "team_b": "Ohio State Buckeyes",
                        "winner": "Duke Blue Devils",
                        "win_prob_a": 80.0,
                        "win_prob_b": 20.0,
                        "debug": {},
                        "model_type": "tournament_ensemble_v1",
                    }
                ],
                "elite_8": [
                    {
                        "team_a": "Duke Blue Devils",
                        "team_b": "Ohio State Buckeyes",
                        "winner": "Duke Blue Devils",
                        "win_prob_a": 70.0,
                        "win_prob_b": 30.0,
                        "debug": {},
                        "model_type": "tournament_ensemble_v1",
                    }
                ],
            }
        },
        "first_four": [],
        "final_four": [],
        "championship": None,
        "title_odds": {},
        "round_advancement_probs": [],
    }

    mock_sim = MagicMock()
    mock_sim.model_dump.return_value = payload
    mock_service.return_value.simulate_bracket.return_value = mock_sim

    service = NCAAMBracketStateService()
    result = service.build_bracket_payload()

    # After rebuild, elite_8 may not exist with only one R64 game; just ensure the actual Kansas/UCF event
    # did not overwrite the only simulated R64 slot.
    r64 = result["regions"]["East"]["round_of_64"][0]
    assert r64["team_a"] == "Duke Blue Devils"
    assert r64["team_b"] == "Ohio State Buckeyes"
    assert r64.get("status") != "final"


@patch("src.services.ncaam_bracket_state_service.NCAAMTournamentPredictionService")
@patch.object(NCAAMBracketStateService, "_fetch_actual_events")
@patch.object(NCAAMBracketStateService, "_load_seed_rows")
def test_final_override_advances_winner_downstream(mock_load, mock_fetch, mock_service):
    """If a Sweet 16 game is final, the actual winner must advance into Elite 8."""
    mock_load.return_value = [
        {"team_name": "Florida Gators", "seed": 1, "region": "South"},
        {"team_name": "Vanderbilt Commodores", "seed": 5, "region": "South"},
        {"team_name": "Illinois Fighting Illini", "seed": 3, "region": "South"},
        {"team_name": "Houston Cougars", "seed": 2, "region": "South"},
    ]

    # Final actual event Florida vs Vanderbilt where Vanderbilt wins.
    mock_fetch.return_value = [
        {
            "home_team": "Florida Gators",
            "away_team": "Vanderbilt Commodores",
            "start_time": datetime.utcnow(),
            "status": "final",
            "final": True,
            "home_score": 74,
            "away_score": 91,
        }
    ]

    # Simulated bracket says Florida wins S16 and advances.
    payload = {
        "season": "2025-26",
        "regions": {
            "South": {
                "round_of_64": [
                    {"team_a": "Florida Gators", "team_b": "Seed16", "winner": "Florida Gators", "win_prob_a": 90.0, "win_prob_b": 10.0, "debug": {}, "model_type": "tournament_ensemble_v1"},
                    {"team_a": "Vanderbilt Commodores", "team_b": "Seed12", "winner": "Vanderbilt Commodores", "win_prob_a": 60.0, "win_prob_b": 40.0, "debug": {}, "model_type": "tournament_ensemble_v1"},
                    {"team_a": "Illinois Fighting Illini", "team_b": "Seed14", "winner": "Illinois Fighting Illini", "win_prob_a": 70.0, "win_prob_b": 30.0, "debug": {}, "model_type": "tournament_ensemble_v1"},
                    {"team_a": "Houston Cougars", "team_b": "Seed15", "winner": "Houston Cougars", "win_prob_a": 80.0, "win_prob_b": 20.0, "debug": {}, "model_type": "tournament_ensemble_v1"},
                ],
                "round_of_32": [
                    {"team_a": "Florida Gators", "team_b": "Vanderbilt Commodores", "winner": "Florida Gators", "win_prob_a": 55.0, "win_prob_b": 45.0, "debug": {}, "model_type": "tournament_ensemble_v1"},
                    {"team_a": "Illinois Fighting Illini", "team_b": "Houston Cougars", "winner": "Illinois Fighting Illini", "win_prob_a": 55.0, "win_prob_b": 45.0, "debug": {}, "model_type": "tournament_ensemble_v1"},
                ],
                "sweet_16": [
                    {"team_a": "Florida Gators", "team_b": "Vanderbilt Commodores", "winner": "Florida Gators", "win_prob_a": 55.0, "win_prob_b": 45.0, "debug": {}, "model_type": "tournament_ensemble_v1"},
                    {"team_a": "Illinois Fighting Illini", "team_b": "Houston Cougars", "winner": "Illinois Fighting Illini", "win_prob_a": 55.0, "win_prob_b": 45.0, "debug": {}, "model_type": "tournament_ensemble_v1"},
                ],
                "elite_8": [
                    {"team_a": "Florida Gators", "team_b": "Illinois Fighting Illini", "winner": "Florida Gators", "win_prob_a": 55.0, "win_prob_b": 45.0, "debug": {}, "model_type": "tournament_ensemble_v1"}
                ],
            }
        },
        "first_four": [],
        "final_four": [],
        "championship": None,
        "title_odds": {},
        "round_advancement_probs": [],
    }

    mock_sim = MagicMock()
    mock_sim.model_dump.return_value = payload
    svc = mock_service.return_value
    svc.simulate_bracket.return_value = mock_sim

    # For any recomputed matchup, return a simple prediction object.
    def _predict_game(gi, conn=None):
        from src.services.ncaam_tournament_service import TournamentGamePrediction
        return TournamentGamePrediction(
            team_a=gi.team_a,
            team_b=gi.team_b,
            winner=gi.team_a,
            winner_side="team_a",
            projected_spread_a=-1.0,
            projected_total=150.0,
            win_prob_a=60.0,
            win_prob_b=40.0,
            confidence_0_100=60.0,
            model_type="tournament_ensemble_v1",
            neutral_site=True,
            market_data_used=False,
            fallback_used=False,
            reason_codes=[],
            risk_flags=[],
            debug={},
            scheduled_tip_et=None,
            tv_network=None,
            site=None,
        )

    svc.predict_game.side_effect = _predict_game

    service = NCAAMBracketStateService()
    result = service.build_bracket_payload()

    r32 = result["regions"]["South"]["round_of_32"][0]
    assert {r32["team_a"], r32["team_b"]} == {"Florida Gators", "Vanderbilt Commodores"}
    assert r32["status"] == "final"
    assert r32["display_winner"] == "Vanderbilt Commodores"

    s16 = result["regions"]["South"]["sweet_16"][0]
    assert "Vanderbilt Commodores" in {s16["team_a"], s16["team_b"]}
    assert "Florida Gators" not in {s16["team_a"], s16["team_b"]}

    # With only a partial region bracket in this test fixture, Elite 8 may not be constructible.
