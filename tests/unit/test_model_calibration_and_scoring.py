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


def test_calibration_validator_rejects_degenerate_and_stale_curves(monkeypatch):
    from src.utils.model_calibration import is_valid_winprob_calibration, load_winprob_calibration

    stale_degenerate = {
        "season": "2025-26",
        "season_start": "2025-11-01",
        "n_obs": 2747,
        "points": [
            {"p": 0.18, "p_cal": 0.10},
            {"p": 0.63, "p_cal": 0.456},
        ],
    }
    assert is_valid_winprob_calibration(stale_degenerate, min_obs=75, min_max_pcal=0.52) is False
    assert (
        is_valid_winprob_calibration(
            {**stale_degenerate, "points": [{"p": 0.40, "p_cal": 0.42}, {"p": 0.60, "p_cal": 0.58}]},
            min_obs=75,
            min_max_pcal=0.52,
            min_season_start="2026-11-01",
        )
        is False
    )

    monkeypatch.setattr("src.database.get_model_param", lambda k: stale_degenerate)
    loaded = load_winprob_calibration(
        "winprob_calibration_ncaam",
        "winprob_calibration_ncaam.json",
        min_obs=75,
        min_max_pcal=0.52,
        min_season_start="2026-11-01",
    )
    assert loaded.get("points") == []


def test_ncaam_total_requires_higher_ev_than_spread():
    m = NCAAMMarketFirstModelV2()
    m._archetype_stats = {}
    rec_spread = {"market": "SPREAD", "side": "HOME", "ev": 0.025, "edge_points": 1.6}
    rec_total = {"market": "TOTAL", "side": "OVER", "ev": 0.025, "edge_points": 1.6}
    rec_total_strong = {"market": "TOTAL", "side": "OVER", "ev": 0.042, "edge_points": 1.6}

    # Stub archetype stats so CI check allows passing once min_ev & override thresholds are met
    m._get_archetype_stats = lambda key: {"n": 80, "mean": 0.04, "sd": 0.10}
    assert m._passes_publish_gates(rec_spread, market_line_home=-3.5, torvik_ok=True) is True
    assert m._passes_publish_gates(rec_total, market_line_home=None, torvik_ok=True) is False
    assert m._passes_publish_gates(rec_total_strong, market_line_home=None, torvik_ok=True) is True


def test_mlb_totals_and_late_season_thresholds():
    model = MLBModel()
    model._winprob_calibration = {"n_obs": 0, "points": []}
    snap = {
        "spread_home": -1.5,
        "spread_price_home": -110,
        "spread_price_away": -110,
        "total": 8.5,
        "total_over_price": -110,
        "total_under_price": -110,
    }
    base_kwargs = {
        "mu_market_spread": -1.5,
        "mu_final_spread": -2.0,
        "mu_market_total": 8.5,
        "mu_final_total": 9.10,
        "prob_home_cover": 0.56,
        "prob_away_cover": 0.44,
        "prob_home_win": 0.55,
        "prob_away_win": 0.45,
        "prob_over": 0.559,
        "prob_under": 0.441,
        "spread_edge": 0.5,
        "ml_edge_home": 0.01,
        "ml_edge_away": 0.0,
        "total_edge": 0.60,
        "nrfi_result": {"p_nrfi": 0.50},
        "home_team": "Yankees",
        "away_team": "Red Sox",
        "ml_home_price": -120,
        "ml_away_price": 100,
        "market_snapshot": snap,
        "has_spread": True,
        "has_total": True,
        "home_data_conf": 0.9,
        "away_data_conf": 0.9,
    }

    # 0.60 run total edge passes old 0.55 bar but is now rejected by 0.65 MIN_EDGE_TOTAL
    early_recs = model._generate_recommendations(**base_kwargs, is_late_season=False)
    early_markets = {r["market_type"] for r in early_recs}
    assert "SPREAD" in early_markets
    assert "TOTAL" not in early_markets

    # 0.72 run edge & 0.565 prob (~7.8% EV) passes in June, but gets blocked by late-season Aug-Sep bump if EV is marginal
    late_marginal = dict(base_kwargs, total_edge=0.70, prob_over=0.560, spread_edge=0.5, prob_home_cover=0.555)
    recs_june = model._generate_recommendations(**late_marginal, is_late_season=False)
    recs_sep = model._generate_recommendations(**late_marginal, is_late_season=True)
    assert len(recs_june) > len(recs_sep)


def test_ncaam_prevents_correlated_spread_and_ml_double_persistence(monkeypatch):
    from datetime import datetime, timedelta, timezone

    model = NCAAMMarketFirstModelV2()
    model._winprob_calibration = {"n_obs": 0, "points": []}
    model.torvik_service = MagicMock()
    model.torvik_service.get_projection.return_value = {"margin": 6.5, "official_margin": 6.5, "total": 144.0, "lean": "Duke Blue Devils"}
    model.torvik_service.get_matchup_team_stats.return_value = {"game_tempo": 68.0, "home": {"luck": 0.0, "continuity": 75.0}, "away": {"luck": 0.0, "continuity": 75.0}}
    model.kenpom_client = MagicMock()
    model.kenpom_client.calculate_kenpom_adjustment.return_value = {"spread_adj": 0.0, "total_adj": 0.0, "summary": ""}
    model.kenpom_client.get_team_player_agg.return_value = None
    model.kenpom_client.get_team_rating.return_value = None
    model.kenpom_client.get_home_court.return_value = None
    model.kenpom_client.get_player_stats_for_team.return_value = []
    model.geo_service = MagicMock()
    model.geo_service.get_altitude_adjustment.return_value = 0.0
    model.geo_service.calculate_distance.return_value = 200.0

    monkeypatch.setattr(model, "_calculate_shooting_regression", lambda *a, **kw: 0.0)
    monkeypatch.setattr(model, "_calculate_situational_spots", lambda *a, **kw: 0.0)
    monkeypatch.setattr(model, "_calculate_fatigue_penalty", lambda *a, **kw: 0.0)
    monkeypatch.setattr(model, "_apply_referee_signal", lambda eid, tot: tot)
    monkeypatch.setattr(model, "_passes_publish_gates", lambda *a, **kw: True)

    persisted_docs = []
    monkeypatch.setattr("src.models.ncaam_market_first_model_v2.insert_model_prediction", lambda doc: persisted_docs.append(doc))

    future_tip = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
    event = {
        "id": "evt_dedupe_ml",
        "home_team": "Duke Blue Devils",
        "away_team": "Army Black Knights",
        "start_time": future_tip,
    }
    snap = {
        "spread_home": -3.5,
        "spread_price_home": -110,
        "spread_price_away": -110,
        "total": 144.0,
        "total_over_price": -110,
        "total_under_price": -110,
        "moneyline_price_home": -135,
        "moneyline_price_away": 115,
    }
    model.analyze("evt_dedupe_ml", event_context=event, market_snapshot=snap, persist=True)
    # Home SPREAD (-3.5) is persisted; step 10b MUST suppress correlated Home MONEYLINE double exposure
    persisted_markets = [d["market_type"] for d in persisted_docs]
    assert "SPREAD" in persisted_markets
    assert "MONEYLINE" not in persisted_markets

    # When no SPREAD is persisted on that game/side, a qualifying standalone ML row IS persisted
    persisted_docs.clear()
    monkeypatch.setattr(model, "_passes_publish_gates", lambda rec, *a, **kw: str(rec.get("market") or "").upper() != "SPREAD")
    model.analyze("evt_ml_only", event_context=event, market_snapshot=snap, persist=True)
    assert "MONEYLINE" in [d["market_type"] for d in persisted_docs]





