import pytest


def test_all_games_learning_bias_sigma_and_feed_accuracy():
    from src.services.archetype_learning_service import (
        fit_adaptive_learning_from_rows,
        fit_all_games_learning,
    )

    # Simulate 50 completed lined games where:
    # - actual scoring runs +4.0 pts higher than fair_total
    # - model sigma_spread is over-inflated (15.0) vs realized spread residual SD (~9.0)
    # - KenPom is sharper than Haslametrics
    slate_rows = []
    for i in range(50):
        sign = 1.0 if i % 2 == 0 else -1.0
        # Spread residual alternates +/-9 around market (-4.0)
        mkt_sp = -4.0
        actual_margin_home = 4.0 + (sign * 9.0)  # home - away
        away_score = 70.0
        home_score = away_score + actual_margin_home
        fair_tot = (home_score + away_score) - 4.0
        mkt_tot = fair_tot + 0.5  # model leans UNDER by 0.5 while actual goes OVER
        slate_rows.append(
            {
                "event_id": f"evt:{i}",
                "home_score": home_score,
                "away_score": away_score,
                "context_json": {
                    "current_spread_home": mkt_sp,
                    "fair_spread_home": mkt_sp - (1.0 * sign),
                    "kenpom_spread_home": mkt_sp - (2.0 * sign),
                    "torvik_spread_home": mkt_sp - (1.0 * sign),
                    "hasla_spread_home": mkt_sp + (3.0 * sign),
                    "current_total": mkt_tot,
                    "fair_total": fair_tot,
                    "sigma_spread": 15.0,
                    "sigma_total": 19.0,
                },
            }
        )

    summary = fit_all_games_learning(slate_rows)
    assert summary["n_games"] == 50
    assert summary["total_bias_sample"] == 50
    # 50/(50+25) * 4.0 = 2.667 -> clamped to +2.5
    assert summary["total_bias_pts"] == pytest.approx(2.5, abs=0.01)

    sig = summary["sigma_calibration"]
    assert sig["spread_n"] == 50
    assert sig["spread_realized_sd"] < 10.0
    assert sig["spread_model_avg_sigma"] == pytest.approx(15.0, abs=0.01)
    assert 0.88 <= sig["spread_sigma_scale"] < 0.96

    feeds = summary["feed_accuracy"]
    assert feeds["kenpom"]["mae"] < feeds["haslametrics"]["mae"]
    assert feeds["kenpom"]["ats_win_rate"] == 1.0
    assert feeds["haslametrics"]["ats_win_rate"] == 0.0

    # Even with ZERO published bets (rows=[]), adaptive learning now picks up full-slate bias & sigma scale
    payload = fit_adaptive_learning_from_rows([], baseline_bins={}, all_games_rows=slate_rows)
    assert payload["total_graded"] == 0  # official published-bet count stays untouched
    la = payload["learned_adjustments"]
    assert la["total_bias_source"] == "all_completed_games"
    assert la["total_bias_sample"] == 50
    assert la["total_bias_pts"] == pytest.approx(2.5, abs=0.01)
    assert 0.88 <= la["spread_sigma_scale"] < 0.96
    assert payload["all_games_summary"]["n_games"] == 50


def test_model_sign_fix_et_date_and_calendar_rest(monkeypatch):
    from contextlib import contextmanager
    from datetime import datetime, timezone
    from unittest.mock import MagicMock
    from src.models.ncaam_market_first_model_v2 import NCAAMMarketFirstModelV2

    model = NCAAMMarketFirstModelV2()

    # 1. Eastern Time date conversion: 8:00 PM ET on Nov 21 = 01:00 UTC on Nov 22 -> "20261121"
    assert model._to_et_yyyymmdd("2026-11-22T01:00:00Z") == "20261121"
    assert model._to_et_yyyymmdd(datetime(2026, 11, 22, 1, 0, tzinfo=timezone.utc)) == "20261121"

    # 2. 46-hour turnaround across 2 ET calendar days (Nov 18 9:00 PM ET -> Nov 20 7:00 PM ET) is NOT a back-to-back
    @contextmanager
    def _dummy_conn():
        yield object()

    class _DummyCur:
        def fetchall(self):
            return [
                {
                    "id": "prev1",
                    "home_team": "Indiana Hoosiers",
                    "away_team": "Other Team",
                    "start_time": datetime(2026, 11, 19, 2, 0, tzinfo=timezone.utc),  # Nov 18 9:00 PM ET
                }
            ]

    monkeypatch.setattr("src.database.get_db_connection", _dummy_conn)
    monkeypatch.setattr("src.database._exec", lambda conn, q, params=None: _DummyCur())
    curr_game = datetime(2026, 11, 21, 0, 0, tzinfo=timezone.utc)  # Nov 20 7:00 PM ET (46h later)
    assert model._calculate_fatigue_penalty("Indiana Hoosiers", "curr1", curr_game) == 0.0

    # 3. Inverted sign fix: penalized home team (fatigue/spot/shooting < 0) moves fair spread UP (less negative / fades home)
    model.torvik_service = MagicMock()
    model.torvik_service.get_projection.return_value = {"margin": 4.0, "official_margin": 4.0, "total": 146.0, "lean": "Home"}
    model.torvik_service.get_matchup_team_stats.return_value = {
        "game_tempo": 68.0,
        "home": {"luck": 0.0, "continuity": 0.75, "record": "12-4"},
        "away": {"luck": 0.0, "continuity": 0.75, "record": "12-4"},
    }
    model.kenpom_client = MagicMock()
    model.kenpom_client.calculate_kenpom_adjustment.return_value = {
        "spread_adj": 4.0, "fair_margin": 4.0, "fair_total": 146.0, "total_adj": 0.0, "summary": "KP"
    }
    model.kenpom_client.get_team_player_agg.return_value = None
    model.kenpom_client.get_team_rating.return_value = None
    model.kenpom_client.get_home_court.return_value = None
    model.kenpom_client.get_player_stats_for_team.return_value = []
    model.haslametrics_client = MagicMock()
    model.haslametrics_client.calculate_projection.return_value = {"available": True, "margin": 4.0, "total": 146.0}
    model.geo_service = MagicMock()
    model.geo_service.get_altitude_adjustment.return_value = 0.0
    model.geo_service.calculate_distance.return_value = 100.0
    model.injury_service = MagicMock()
    model.injury_service.get_matchup_injuries.return_value = {"has_injuries": False, "injuries": []}
    model.news_service = MagicMock()
    model.news_service.fetch_game_context.return_value = {}
    model.news_service.summarize_impact.return_value = ""
    monkeypatch.setattr(model, "_get_council_verdict", lambda eid: None)
    monkeypatch.setattr(model, "_apply_referee_signal", lambda eid, tot, avg_ftr=None: tot)
    monkeypatch.setattr(model, "_load_winprob_calibration", lambda: {"points": []})
    monkeypatch.setattr(model, "_load_adaptive_learning", lambda: {})
    monkeypatch.setattr(model, "_calculate_shooting_regression", lambda t, as_of_date=None: -1.0 if t == "Home" else 0.0)
    monkeypatch.setattr(model, "_calculate_situational_spots", lambda t, ev: -0.8 if t == "Home" else 0.0)
    monkeypatch.setattr(model, "_calculate_fatigue_penalty", lambda t, eid, gd: -0.7 if t == "Home" else 0.0)

    ev = {"id": "evt_sign_fix", "home_team": "Home", "away_team": "Away", "start_time": datetime(2027, 1, 20, 20, 0, tzinfo=timezone.utc)}
    res = model.analyze("evt_sign_fix", event_context=ev, market_snapshot={"spread_home": -4.0, "total": 146.0}, relax_gates=True, persist=False)
    # Market is -4.0 and all feeds match -4.0, so home penalty pushes mu_spread_final > -4.0 (less favored)
    assert res["debug"]["mu_spread_final"] > -2.5
