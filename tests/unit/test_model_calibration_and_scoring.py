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


def test_shared_pava_interpolation_and_min_obs_guard():
    from src.utils.model_calibration import interpolate_pava_prob

    cal = {
        "n_obs": 250,
        "points": [
            {"p": 0.40, "p_cal": 0.35},
            {"p": 0.60, "p_cal": 0.55},
        ],
    }
    assert round(interpolate_pava_prob(0.50, cal, min_obs=200), 4) == 0.45
    assert round(interpolate_pava_prob(0.50, cal, min_obs=200, blend_weight=0.5), 4) == 0.475
    assert interpolate_pava_prob(0.50, {**cal, "n_obs": 116}, min_obs=200) == 0.50


def test_ncaam_ml_persist_gate_blocks_longshots_and_thin_edges():
    m = NCAAMMarketFirstModelV2.__new__(NCAAMMarketFirstModelV2)
    # +320 longshot with weak win_prob fails even if raw EV > 0.05
    assert m._passes_ml_persist_gates(win_prob=0.28, ev=0.176, price=320) is False
    # Marginal +3% EV passes old 2% threshold but fails new 5% ML threshold
    assert m._passes_ml_persist_gates(win_prob=0.56, ev=0.03, price=-118) is False
    # Heavy favorite deeper than -250 fails
    assert m._passes_ml_persist_gates(win_prob=0.80, ev=0.08, price=-300) is False
    # Solid short favorite within -250..+185 with >=45% prob, >=5% EV, >=3% prob edge passes
    assert m._passes_ml_persist_gates(win_prob=0.58, ev=0.06, price=-115) is True


def test_stale_empty_score_history_row_voids_after_14_days():
    from datetime import datetime, timedelta, timezone
    from src.utils.model_performance import normalize_history_row

    old_start = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    recent_start = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()

    stale_postponed = normalize_history_row({
        "sport": "NCAAM",
        "market_type": "SPREAD",
        "outcome": None,
        "final": False,
        "score": None,
        "start_time": old_start,
    })
    assert stale_postponed["outcome"] == "VOID"

    recent_ungraded = normalize_history_row({
        "sport": "NCAAM",
        "market_type": "SPREAD",
        "outcome": None,
        "final": False,
        "score": None,
        "start_time": recent_start,
    })
    assert recent_ungraded["outcome"] == "PENDING"


def test_pava_quantile_pooling_prevents_tail_collapse():
    # Single lowest-p miss + 149 well-calibrated rows shouldn't collapse p_cal to 0.01
    obs = [Obs(p=0.520, y=0)]
    for i in range(1, 150):
        p = 0.52 + (i / 150.0) * 0.30
        obs.append(Obs(p=p, y=1 if (i % 2 == 0 or p > 0.65) else 0))

    art = fit_calibration_artifact(obs, days=365, min_points=12)
    assert art["points"][0]["p_cal"] >= 0.30
    assert art["points"][-1]["p_cal"] <= 0.99


def test_ncaam_and_mlb_calibration_blend_preserves_strong_edges():
    ncaam = NCAAMMarketFirstModelV2.__new__(NCAAMMarketFirstModelV2)
    ncaam._winprob_calibration = {
        "n_obs": 2747,
        "points": [
            {"p": 0.18, "p_cal": 0.10},
            {"p": 0.40, "p_cal": 0.32},
            {"p": 0.63, "p_cal": 0.46},
        ],
    }
    # Strong 58% raw signal stays above -110 break-even (52.4%) while marginal 53% is shrunk below it
    assert ncaam._calibrate_win_prob(0.58) >= 0.54
    assert ncaam._calibrate_win_prob(0.53) < 0.51

    mlb = MLBModel()
    mlb._winprob_calibration = {
        "n_obs": 790,
        "points": [
            {"p": 0.547, "p_cal": 0.421},
            {"p": 0.582, "p_cal": 0.521},
            {"p": 0.756, "p_cal": 0.611},
        ],
    }
    assert mlb._calibrate_win_prob(0.60) >= 0.57
    assert mlb._calibrate_win_prob(0.545) < 0.51



