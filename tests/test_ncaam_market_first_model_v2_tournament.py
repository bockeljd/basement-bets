from datetime import datetime

import pytest

from src.models.ncaam_market_first_model_v2 import NCAAMMarketFirstModelV2


class _TorvikStub:
    def __init__(self, margin: float, total: float = 150.0):
        self._margin = margin
        self._total = total

    def get_projection(self, team_a, team_b, date=None, conn=None):
        # In the model code, mu_base_spread = -(torvik_view['margin']).
        return {"lean": "A", "margin": self._margin, "total": self._total}

    def get_matchup_team_stats(self, team_a, team_b, date=None):
        return {"game_tempo": 68.0}


class _KenPomStub:
    def calculate_kenpom_adjustment(self, team_a, team_b, conn=None):
        # Return None so the model uses Torvik spread directly (no blending)
        return None


class _TournamentFeaturesStub:
    def get_tournament_modifiers(self, team, conn=None):
        return {
            "luck_adj_points": 0,
            "continuity_adj_points": 0,
            "turnover_adj_points": 0,
            "q1_adj_points": 0,
            "variance_multiplier": 1.0,
            "upset_risk_score": 0,
        }


@pytest.mark.parametrize(
    "mu_spread_final, expected_winner_side",
    [
        (-23.0, "team_a"),  # team_a heavily favored
        (23.0, "team_b"),   # team_b heavily favored
    ],
)
def test_tournament_win_prob_directionality(mu_spread_final, expected_winner_side):
    model = NCAAMMarketFirstModelV2()

    # Choose torvik margin such that mu_base_spread = -(margin) == mu_spread_final
    # (no modifiers, no market blending)
    torvik_margin = -mu_spread_final

    model.torvik_service = _TorvikStub(margin=torvik_margin)
    model.kenpom_client = _KenPomStub()
    model.tournament_features = _TournamentFeaturesStub()

    res = model.analyze_tournament_game(
        team_a="Duke Blue Devils",
        team_b="Siena Saints",
        event_context={"start_time": datetime.utcnow()},
        market_snapshot=None,
        persist=False,
        neutral_site=True,
        conn=None,
    )

    assert res["projected_spread_a"] == round(mu_spread_final, 2)
    assert res["winner_side"] == expected_winner_side

    if expected_winner_side == "team_a":
        assert res["win_prob_a"] > 50.0
        assert res["win_prob_b"] < 50.0
    else:
        assert res["win_prob_b"] > 50.0
        assert res["win_prob_a"] < 50.0


def test_season_date_helpers_november_2026():
    from src.utils.ncaam_season import normalize_iso_date, season_start_date_for_game

    assert normalize_iso_date("20261111") == "2026-11-11"
    assert normalize_iso_date("2026-11-11T19:00:00Z") == "2026-11-11"
    assert season_start_date_for_game("20261111") == "2026-11-01"
    assert season_start_date_for_game("2027-03-20") == "2026-11-01"


def test_kenpom_adjustment_pace_scaled_margin():
    from unittest.mock import MagicMock
    from src.services.kenpom_client import KenPomClient

    client = KenPomClient()
    client.get_team_rating = MagicMock(
        side_effect=[
            {"team": "Duke", "rank": 3, "adj_em": 25.0, "adj_o": 120.0, "adj_d": 95.0, "adj_t": 70.0},
            {"team": "Siena", "rank": 200, "adj_em": 5.0, "adj_o": 102.0, "adj_d": 97.0, "adj_t": 66.0},
        ]
    )
    adj_home = client.calculate_kenpom_adjustment("Duke", "Siena", neutral_site=False)
    # em_diff = 20.0, avg_tempo = 68.0 -> neutral_margin = 13.6, fair_margin = 16.8
    assert adj_home["neutral_margin"] == 13.6
    assert adj_home["fair_margin"] == 16.8
    assert adj_home["spread_adj"] == 16.8

    client.get_team_rating = MagicMock(
        side_effect=[
            {"team": "Duke", "rank": 3, "adj_em": 25.0, "adj_o": 120.0, "adj_d": 95.0, "adj_t": 70.0},
            {"team": "Siena", "rank": 200, "adj_em": 5.0, "adj_o": 102.0, "adj_d": 97.0, "adj_t": 66.0},
        ]
    )
    adj_neutral = client.calculate_kenpom_adjustment("Duke", "Siena", neutral_site=True)
    assert adj_neutral["neutral_margin"] == 13.6
    assert adj_neutral["fair_margin"] == 13.6
    assert adj_neutral["spread_adj"] == 13.6


def test_early_season_weights_and_bundled_params(monkeypatch):
    import os
    model = NCAAMMarketFirstModelV2()

    # November dynamic weights scale down both Torvik and KenPom
    nov_dt = datetime(2026, 11, 11, 19, 0, 0)
    assert model._get_dynamic_weights(nov_dt) == 0.12
    assert model._get_dynamic_kenpom_weight(nov_dt, avg_continuity=0.75) == pytest.approx(0.10)
    assert model._get_dynamic_kenpom_weight(nov_dt, avg_continuity=0.40) == pytest.approx(0.08)

    # Bundled model params resolve from src/services/model_params
    for fname in (
        "action_network_archetype_stats_ncaam.json",
        "winprob_calibration_ncaam.json",
        "model_confidence_params_ncaam.json",
    ):
        resolved = model._resolve_model_param_path(fname)
        assert os.path.exists(resolved), f"Missing {fname} at {resolved}"
        assert "src/services/model_params" in resolved.replace("\\", "/")

    # Unassigned referee crew should not modify mu_total
    monkeypatch.setattr("src.database.get_referee_assignment", lambda event_id: {})
    assert model._apply_referee_signal("evt_no_refs", 145.5) == 145.5


def test_analyze_november_big_favorite_no_kenpom_bias_and_outer_cap(monkeypatch):
    from unittest.mock import MagicMock

    model = NCAAMMarketFirstModelV2()
    model.torvik_service = MagicMock()
    model.torvik_service.get_projection.return_value = {
        "margin": 15.0,
        "official_margin": 15.0,
        "total": 148.0,
        "lean": "Duke",
    }
    model.torvik_service.get_matchup_team_stats.return_value = {
        "game_tempo": 68.0,
        "home": {"luck": 0.08, "continuity": 75.0, "record": "1-0"},
        "away": {"luck": -0.08, "continuity": 75.0, "record": "1-0"},
    }

    model.kenpom_client = MagicMock()
    model.kenpom_client.calculate_kenpom_adjustment.return_value = {
        "spread_adj": 15.0,
        "neutral_margin": 11.8,
        "fair_margin": 15.0,
        "total_adj": 0.0,
        "summary": "KenPom: Duke (#3) vs Siena (#200)",
    }
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
    monkeypatch.setattr(model, "_generate_recommendations", lambda *a, **kw: [])

    event = {
        "id": "evt_nov_1",
        "home_team": "Duke Blue Devils",
        "away_team": "Siena Saints",
        "start_time": datetime(2026, 11, 11, 19, 0, 0),
    }
    snap = {"spread_home": -15.0, "total": 148.0}
    res = model.analyze("evt_nov_1", event_context=event, market_snapshot=snap, relax_gates=True, persist=False)
    # Both Torvik (+15) and KenPom (+15) match the -15.0 market spread, and <4 games played suppresses luck noise
    assert res["debug"]["mu_spread_final"] == pytest.approx(-15.0, abs=0.05)

    # Even if situational signals fire heavily, outer cap clamps within CAP_SPREAD + 1.0 (3.0 pts) of market (-15.0)
    monkeypatch.setattr(model, "_calculate_shooting_regression", lambda team, **kw: -2.0 if "Duke" in team else 1.0)
    monkeypatch.setattr(model, "_calculate_situational_spots", lambda team, ev: -1.5 if "Duke" in team else 0.0)
    monkeypatch.setattr(model, "_calculate_fatigue_penalty", lambda team, eid, gd: -2.5 if "Duke" in team else 0.0)
    res_clamped = model.analyze("evt_nov_1", event_context=event, market_snapshot=snap, relax_gates=True, persist=False)
    assert abs(res_clamped["debug"]["mu_spread_final"] - (-15.0)) <= 3.0 + 1e-6


def test_team_matcher_disambiguation():
    from src.utils.team_matcher import TeamMatcher

    matcher = TeamMatcher()
    TeamMatcher._source_names_cache[("bt_team_metrics_daily", "team_text")] = [
        "Kansas",
        "UMKC",
        "Penn",
        "Penn St.",
        "Oklahoma",
        "Oklahoma St.",
        "Southern",
        "SMU",
        "California",
        "Cal Baptist",
        "Kentucky",
        "Morgan St.",
        "Maryland Eastern Shore",
        "N.C. State",
        "North Carolina",
    ]

    assert matcher.find_source_name("Kansas City Roos", "bt_team_metrics_daily", "team_text") == "UMKC"
    assert matcher.find_source_name("Penn State Nittany Lions", "bt_team_metrics_daily", "team_text") == "Penn St."
    assert matcher.find_source_name("Oklahoma State Cowboys", "bt_team_metrics_daily", "team_text") == "Oklahoma St."
    assert matcher.find_source_name("Southern Methodist Mustangs", "bt_team_metrics_daily", "team_text") == "SMU"
    assert matcher.find_source_name("Southern University Jaguars", "bt_team_metrics_daily", "team_text") == "Southern"
    assert matcher.find_source_name("California Baptist Lancers", "bt_team_metrics_daily", "team_text") == "Cal Baptist"
    assert matcher.find_source_name("Morgan State Bears", "bt_team_metrics_daily", "team_text") == "Morgan St."
    assert matcher.find_source_name("Maryland-Eastern Shore Hawks", "bt_team_metrics_daily", "team_text") == "Maryland Eastern Shore"
    assert matcher.find_source_name("North Carolina State Wolfpack", "bt_team_metrics_daily", "team_text") == "N.C. State"
    # Non-D1 school should not false-match Kentucky Wildcats
    assert matcher.find_source_name("Kentucky State Thorobreds", "bt_team_metrics_daily", "team_text") is None



