from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from src.services.grading_backfill import (
    extract_first_inning_totals,
    fetch_espn_scoreboard_finals,
    grade_nrfi_yrfi,
    grade_parlay_legs_from_games,
    match_mlb_schedule_game,
    normalize_mlb_team,
    parse_nrfi_yrfi_pick,
    parse_parlay_legs,
    resolve_team_side,
)
from src.services.grading_service import GradingService


def test_mlb_team_normalization_and_city_disambiguation():
    assert normalize_mlb_team("Oakland Athletics") == normalize_mlb_team("Athletics")
    assert normalize_mlb_team("Cleveland Indians") == "cleveland guardians"
    assert resolve_team_side("HOME", "Los Angeles Dodgers", "Los Angeles Angels", is_mlb=True) == "HOME"
    assert resolve_team_side("AWAY", "Los Angeles Dodgers", "Los Angeles Angels", is_mlb=True) == "AWAY"
    assert resolve_team_side("Los Angeles Angels", "Los Angeles Dodgers", "Los Angeles Angels", is_mlb=True) == "AWAY"
    assert resolve_team_side("Los Angeles Dodgers", "Los Angeles Dodgers", "Los Angeles Angels", is_mlb=True) == "HOME"
    assert resolve_team_side("Athletics", "Sacramento Athletics", "Chicago White Sox", is_mlb=True) == "HOME"


def test_nrfi_yrfi_parsing_and_linescore_grading():
    assert parse_nrfi_yrfi_pick("NRFI") == "NRFI"
    assert parse_nrfi_yrfi_pick("NRFI (San Francisco Giants vs Chicago White Sox)") == "NRFI"
    assert parse_nrfi_yrfi_pick("YRFI", selection="YRFI (Cubs vs Cardinals)") == "YRFI"

    final_zero = {
        "status": "Final",
        "linescore": {
            "currentInning": 9,
            "innings": [{"num": 1, "away": {"runs": 0}, "home": {"runs": 0}}],
        },
    }
    assert extract_first_inning_totals(final_zero) == (0, 0)
    assert grade_nrfi_yrfi("NRFI (Giants vs White Sox)", 0, 0) == "WON"
    assert grade_nrfi_yrfi("YRFI (Giants vs White Sox)", 0, 0) == "LOST"

    final_run = {
        "status": "Final",
        "linescore": {
            "currentInning": 9,
            "innings": [{"num": 1, "away": {"runs": 1}, "home": {"runs": 0}}],
        },
    }
    assert extract_first_inning_totals(final_run) == (1, 0)
    assert grade_nrfi_yrfi("NRFI", 1, 0) == "LOST"
    assert grade_nrfi_yrfi("YRFI", 1, 0) == "WON"

    # Game only in top/bottom 1st must not premake NRFI a win
    unfinished = {
        "status": "In Progress",
        "linescore": {
            "currentInning": 1,
            "innings": [{"num": 1, "away": {"runs": 0}, "home": {"runs": 0}}],
        },
    }
    assert extract_first_inning_totals(unfinished) is None


def test_match_mlb_schedule_doubleheader_tiebreak():
    games = [
        {
            "game_pk": 1001,
            "status": "Final",
            "away_team": "New York Yankees",
            "home_team": "Boston Red Sox",
            "game_date": "2026-06-15T17:10:00Z",
            "home_score": 4,
            "away_score": 2,
        },
        {
            "game_pk": 1002,
            "status": "Final",
            "away_team": "New York Yankees",
            "home_team": "Boston Red Sox",
            "game_date": "2026-06-15T23:10:00Z",
            "home_score": 1,
            "away_score": 6,
        },
    ]
    matched_g2 = match_mlb_schedule_game(
        games,
        "NY Yankees",
        "Boston Red Sox",
        start_time="2026-06-15T23:05:00Z",
    )
    assert matched_g2 is not None
    assert matched_g2["game_pk"] == 1002


def test_parlay_parsing_and_score_based_grading():
    assert parse_parlay_legs("Kansas @ Houston | Parlay: UCLA -6.5 | Arizona -10.5") == [
        "UCLA -6.5",
        "Arizona -10.5",
    ]
    assert parse_parlay_legs("Parlay: Duke ML | Duke @ North Carolina Over 145.5") == [
        "Duke ML",
        "Duke @ North Carolina Over 145.5",
    ]

    games = [
        {"home_team": "UCLA Bruins", "away_team": "USC Trojans", "home_score": 80, "away_score": 70},
        {"home_team": "Arizona Wildcats", "away_team": "Utah Utes", "home_score": 88, "away_score": 75},
    ]
    assert grade_parlay_legs_from_games(["UCLA -6.5", "Arizona -10.5"], games) == "WON"
    assert grade_parlay_legs_from_games(["UCLA -10", "Arizona -10.5"], games) == "WON"  # push + win => WON
    assert grade_parlay_legs_from_games(["UCLA -6.5", "Arizona -14.5"], games) == "LOST"
    assert grade_parlay_legs_from_games(["UCLA -6.5", "Kentucky -4.5"], games) == "PENDING"


def test_grading_service_grade_row_action_id_nrfi_and_moneyline_home():
    svc = GradingService()
    sample_game = {
        "game_pk": 824679,
        "status": "Final",
        "game_date": "2026-05-22T18:20:00Z",
        "home_team": "Chicago Cubs",
        "away_team": "Houston Astros",
        "home_score": 2,
        "away_score": 4,
        "linescore": {
            "currentInning": 9,
            "innings": [{"num": 1, "away": {"runs": 0}, "home": {"runs": 0}}],
        },
    }
    svc._mlb_schedule_cache = {
        "2026-05-21": [],
        "2026-05-22": [sample_game],
        "2026-05-23": [],
    }

    with patch("src.services.mlb_service.MLBService") as mock_mlb_cls:
        outcome = svc._grade_row({
            "event_id": "action:mlb:274512",  # must NOT be mistaken for MLB gamePk
            "league": "MLB",
            "market_type": "NRFI",
            "pick": "NRFI (Houston Astros vs Chicago Cubs)",
            "selection": "NRFI (Houston Astros vs Chicago Cubs)",
            "bet_line": None,
            "home_team": "Chicago Cubs",
            "away_team": "Houston Astros",
            "home_score": 2,
            "away_score": 4,
            "start_time": datetime(2026, 5, 22, 18, 20, tzinfo=timezone.utc),
        })
        assert outcome == "WON"
        mock_mlb_cls.return_value.get_first_inning_scores.assert_not_called()

    ml_outcome = svc._grade_row({
        "event_id": "action:ncaam:99999",
        "league": "NCAAM",
        "market_type": "H2H",
        "pick": "AWAY",
        "selection": "Saint Louis ML",
        "bet_line": None,
        "home_team": "Michigan Wolverines",
        "away_team": "Saint Louis Billikens",
        "home_score": 76,
        "away_score": 55,
    })
    assert ml_outcome == "LOST"


def test_fetch_espn_scoreboard_finals_filters_incomplete_games():
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "events": [
            {
                "id": "401001",
                "date": "2026-01-24T19:00Z",
                "competitions": [{
                    "status": {"type": {"completed": True, "state": "post"}},
                    "competitors": [
                        {"homeAway": "home", "team": {"displayName": "Arizona Wildcats"}, "score": "88"},
                        {"homeAway": "away", "team": {"displayName": "West Virginia Mountaineers"}, "score": "53"},
                    ],
                }],
            },
            {
                "id": "401002",
                "date": "2026-01-24T22:00Z",
                "competitions": [{
                    "status": {"type": {"completed": False, "state": "pre"}},
                    "competitors": [
                        {"homeAway": "home", "team": {"displayName": "Duke Blue Devils"}, "score": "0"},
                        {"homeAway": "away", "team": {"displayName": "NC State Wolfpack"}, "score": "0"},
                    ],
                }],
            },
        ]
    }
    mock_session.get.return_value = mock_resp

    finals = fetch_espn_scoreboard_finals("NCAAM", "20260124", session=mock_session)
    assert len(finals) == 1
    assert finals[0]["home_team"] == "Arizona Wildcats"
    assert finals[0]["home_score"] == 88
    assert finals[0]["away_score"] == 53


def test_evaluate_db_predictions_includes_low_ev_rows():
    svc = GradingService()
    mock_row = {
        "id": 101,
        "event_id": "action:ncaam:12345",
        "market_type": "SPREAD",
        "pick": "Duke Blue Devils",
        "bet_line": -5.5,
        "book": "Consensus",
        "selection": "Duke Blue Devils -5.5",
        "analyzed_at": datetime(2026, 3, 18, 12, 0, tzinfo=timezone.utc),
        "narrative_json": "{}",
        "ev_per_unit": 0.004,
        "league": "NCAAM",
        "home_team": "Duke Blue Devils",
        "away_team": "TCU Horned Frogs",
        "start_time": datetime(2026, 3, 18, 23, 0, tzinfo=timezone.utc),
        "home_score": 81,
        "away_score": 58,
        "final": True,
    }
    mock_conn = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = mock_conn

    with patch("src.services.grading_service.get_db_connection", return_value=mock_ctx), \
         patch("src.services.grading_service._exec") as mock_exec, \
         patch("src.services.grading_service.update_model_prediction_result") as mock_upd:
        mock_exec.return_value.fetchall.return_value = [mock_row]
        graded, results = svc._evaluate_db_predictions(max_rows=500, include_all_ev=True)

        assert graded == 1
        assert len(results) == 1
        mock_upd.assert_called_once_with(101, "WON")
        sql_executed = mock_exec.call_args[0][1]
        assert "ev_per_unit" not in sql_executed.split("WHERE", 1)[1]
