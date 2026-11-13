from unittest.mock import MagicMock, patch

from scripts.build_winprob_calibration_ncaam import Obs, fit_calibration_artifact
from src.models.mlb_model import MLBModel
from src.models.ncaam_market_first_model_v2 import NCAAMMarketFirstModelV2
from src.utils.model_performance import conf_bucket


def test_ncaam_confidence_score_prevents_longshot_inflation():
    m = NCAAMMarketFirstModelV2.__new__(NCAAMMarketFirstModelV2)
    # High-EV (+350 underdog) with 30% win prob MUST be Low confidence (<50), not High (>=80)
    longshot_score = m._confidence_score_0_100(None, fallback_win_prob=0.30, ev_per_unit=0.35)
    assert longshot_score < 50
    assert conf_bucket(longshot_score) == "Low"

    # Medium win-prob pick
    med_score = m._confidence_score_0_100(0.53, fallback_win_prob=0.54, ev_per_unit=0.04)
    assert 50 <= med_score < 80
    assert conf_bucket(med_score) == "Medium"

    # High calibrated win-prob pick
    high_score = m._confidence_score_0_100(0.57, fallback_win_prob=0.60, ev_per_unit=0.09)
    assert 80 <= high_score <= 95
    assert conf_bucket(high_score) == "High"


def test_mlb_runline_probability_respects_home_underdog_spread():
    model = MLBModel()
    model.mlb_service = MagicMock()
    model.nrfi_service = MagicMock()
    model.nrfi_service.LEAGUE_AVG_NRFI_RATE = 0.51
    model.nrfi_service.calculate_nrfi_probability.return_value = {"p_nrfi": 0.50}
    model.ballpark = MagicMock()
    model.ballpark.get_park_factor_runs.return_value = 1.0
    model.ballpark.get_park_factor_hr.return_value = 1.0
    model.ballpark.get_altitude_adjustment.return_value = 0.0
    model.ballpark.calculate_travel_distance.return_value = 200
    model.ballpark.is_domed.return_value = False
    model.weather = MagicMock()
    model.weather.get_game_weather.return_value = None

    model.mlb_service.get_pitcher_season_stats.return_value = {"era": 3.5, "whip": 1.15, "throws": "R"}
    model.mlb_service.get_pitcher_recent_form.return_value = None
    model.mlb_service.get_pitcher_home_away_splits.return_value = None
    model.mlb_service.calculate_pitcher_rating.return_value = {"runs_per_9": 3.5, "confidence": 0.9}
    model.mlb_service.get_team_batting_rating.return_value = {"confidence": 0.9, "runs_per_game": 4.5}
    model.mlb_service.get_platoon_adjustment.return_value = 0.0
    model.mlb_service.get_bullpen_rating.return_value = {"era": 3.8}
    # Slight home projection advantage even when market sets Home +1.5
    model.mlb_service.project_runs.side_effect = [
        {"projected_runs": 4.6},  # home runs
        {"projected_runs": 4.0},  # away runs
    ]

    res = model.analyze(
        event_id="action:mlb:999",
        market_snapshot={
            "spread_home": 1.5,  # Home is +1.5 underdog
            "spread_price_home": -130,
            "spread_price_away": 110,
            "total": 8.5,
            "total_over_price": -110,
            "total_under_price": -110,
            "moneyline_price_home": 105,
            "moneyline_price_away": -125,
        },
        event_context={
            "home_team": "Chicago Cubs",
            "away_team": "Los Angeles Dodgers",
            "start_time": "2026-06-15T18:20:00Z",
        },
        persist=False,
    )
    # Since Home is +1.5 AND model projects Home slightly ahead, prob_home_cover MUST be > 0.50!
    assert res["model"]["prob_home_cover"] > 0.50
    for rec in res["recommendations"]:
        assert "confidence_0_100" in rec
        assert 20 <= rec["confidence_0_100"] <= 95


def test_pava_calibration_artifact_fit():
    obs = [Obs(p=0.45, y=0), Obs(p=0.46, y=0), Obs(p=0.58, y=1), Obs(p=0.60, y=1)] * 5
    art = fit_calibration_artifact(obs, days=180, min_points=6)
    assert art["method"] == "isotonic_pava_piecewise_linear"
    assert art["n_obs"] == 20
    assert len(art["points"]) >= 2
    assert art["points"][0]["p_cal"] <= art["points"][-1]["p_cal"]
