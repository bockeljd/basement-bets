from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

import src.api as api_mod
import src.database as db_mod
from src.config import settings
from src.models.ncaam_market_first_model_v2 import NCAAMMarketFirstModelV2
from src.utils.model_performance import compute_top6_quality_score


def test_ncaam_top6_cutoffs_sql_uses_date_comparison_not_text(monkeypatch):
    seen_queries = []

    @contextmanager
    def _dummy_conn():
        yield object()

    class _DummyResult:
        def __init__(self, row):
            self._row = row

        def fetchone(self):
            return self._row

    def _fake_exec(conn, sql, params=None):
        seen_queries.append(sql)
        if "FROM recommended_slates" in sql:
            return _DummyResult(None)
        return _DummyResult({
            "upcoming_pre_cutoff": 4,
            "latest_computed_at": datetime.now(timezone.utc) - timedelta(hours=2),
            "latest_odds_at": datetime.now(timezone.utc) - timedelta(hours=2),
        })

    monkeypatch.setattr(db_mod, "get_db_connection", _dummy_conn)
    monkeypatch.setattr(db_mod, "_exec", _fake_exec)
    monkeypatch.setattr(settings, "CRON_SECRET", "test-secret")
    monkeypatch.setattr("src.services.ncaam_publisher.publish_slate", lambda: {"status": "rolling"})

    client = TestClient(api_mod.app)
    resp = client.get("/api/jobs/ncaam_top6_cutoffs", headers={"Authorization": "Bearer test-secret"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["stale_refresh_needed"] is True

    dtp_queries = [q for q in seen_queries if "daily_top_picks" in q]
    assert dtp_queries
    assert "::date::text" not in dtp_queries[0]
    assert "::date" in dtp_queries[0]


def test_november_situational_clamp_bounds_heuristic_noise_while_keeping_injuries(monkeypatch):
    def _make_model(inj_adj: float) -> NCAAMMarketFirstModelV2:
        m = NCAAMMarketFirstModelV2()
        m.torvik_service = MagicMock()
        m.torvik_service.get_projection.return_value = {"margin": 1.4, "official_margin": 1.4, "total": 149.0, "lean": "Home"}
        m.torvik_service.get_matchup_team_stats.return_value = {
            "game_tempo": 68.0,
            "home": {"luck": 0.0, "continuity": 0.65, "record": "3-2"},
            "away": {"luck": 0.0, "continuity": 0.65, "record": "3-2"},
        }
        m.kenpom_client = MagicMock()
        m.kenpom_client.calculate_kenpom_adjustment.return_value = {
            "spread_adj": 2.4, "fair_margin": 2.4, "fair_total": 150.0, "total_adj": 0.0, "summary": "KP"
        }
        m.kenpom_client.get_team_player_agg.return_value = None
        m.kenpom_client.get_team_rating.return_value = None
        m.kenpom_client.get_home_court.return_value = {"hca": 4.8}
        m.kenpom_client.get_player_stats_for_team.return_value = []
        m.haslametrics_client = MagicMock()
        m.haslametrics_client.calculate_projection.return_value = {"available": False}
        m.geo_service = MagicMock()
        m.geo_service.get_altitude_adjustment.return_value = 0.6
        m.geo_service.calculate_distance.return_value = 1500.0
        m.injury_service = MagicMock()
        m.injury_service.get_matchup_injuries.return_value = {
            "has_injuries": bool(inj_adj),
            "injuries": [],
            "spread_adj": inj_adj,
            "total_adj": 0.0,
        }
        m.news_service = MagicMock()
        m.news_service.fetch_game_context.return_value = {}
        m.news_service.summarize_impact.return_value = ""
        monkeypatch.setattr(m, "_get_council_verdict", lambda eid: None)
        monkeypatch.setattr(m, "_apply_referee_signal", lambda eid, tot, avg_ftr=None: tot)
        monkeypatch.setattr(m, "_load_winprob_calibration", lambda: {"points": []})
        monkeypatch.setattr(m, "_load_adaptive_learning", lambda: {})
        monkeypatch.setattr(m, "_calculate_shooting_regression", lambda t, as_of_date=None: 1.0 if t == "Home" else 0.0)
        monkeypatch.setattr(m, "_calculate_situational_spots", lambda t, ev: 0.5 if t == "Home" else 0.0)
        monkeypatch.setattr(m, "_calculate_fatigue_penalty", lambda t, eid, gd: 0.7 if t == "Home" else 0.0)
        return m

    ev = {"id": "evt_nov_sit", "home_team": "Home", "away_team": "Away", "start_time": datetime(2026, 11, 24, 23, 0, tzinfo=timezone.utc)}
    snap = {"spread_home": -1.75, "spread_price_home": -105, "total": 149.0}

    no_inj = _make_model(0.0).analyze("evt_nov_sit", event_context=ev, market_snapshot=snap, relax_gates=True, persist=False)
    mu_no_inj = no_inj["debug"]["mu_spread_final"]
    # agree_count == 0 in November -> market (-1.75) + tiny rating shift - max 0.50 situational shift -> within 0.65 pts of market
    assert abs(mu_no_inj - (-1.75)) <= 0.65

    with_inj = _make_model(-1.2).analyze("evt_nov_sit", event_context=ev, market_snapshot=snap, relax_gates=True, persist=False)
    mu_with_inj = with_inj["debug"]["mu_spread_final"]
    # Real injury shift (-1.2) is applied outside the 0.50 situational clamp cleanly
    assert abs((mu_with_inj - mu_no_inj) - (-1.2)) < 0.05


def test_smart_risk_rejects_zero_consensus_retail_lag_but_allows_consensus_or_steam(monkeypatch):
    model = NCAAMMarketFirstModelV2()
    model._get_archetype_stats = lambda k: {"n": 80, "mean": 0.03, "sd": 0.10}
    monkeypatch.setattr(model, "_load_adaptive_learning", lambda: {})

    retail_lag_only = {
        "market": "SPREAD",
        "side": "home",
        "ev": 0.073,
        "edge_points": 2.0,
        "win_prob_lb10": 0.513,
        "_agree_count": 0,
        "sharp_edge_pts": 0.5,
        "movement_tags": ["sharp_price_edge"],
    }
    assert model._passes_publish_gates(retail_lag_only, -1.5, True) is False

    rlm_backed = {
        "market": "SPREAD",
        "side": "home",
        "ev": 0.042,
        "edge_points": 1.6,
        "win_prob_lb10": 0.512,
        "_agree_count": 0,
        "movement_tags": ["rlm_confirmed"],
    }
    assert model._passes_publish_gates(rlm_backed, -1.5, True) is True
    assert rlm_backed["is_smart_risk"] is True

    two_model_consensus = {
        "market": "SPREAD",
        "side": "home",
        "ev": 0.040,
        "edge_points": 1.8,
        "win_prob_lb10": 0.512,
        "_agree_count": 2,
    }
    assert model._passes_publish_gates(two_model_consensus, -4.5, True) is True
    assert two_model_consensus["is_smart_risk"] is True


def test_core_consensus_outranks_smart_risk_in_quality_score():
    core_3of3 = {
        "market_type": "SPREAD",
        "side": "away",
        "bet_line": 1.5,
        "ev_per_unit": 0.050,
        "win_prob_lb10": 0.523,
        "conviction_sources": 3,
        "is_smart_risk": False,
        "risk_tier": "CORE",
    }
    smart_risk_zero_agree = {
        "market_type": "SPREAD",
        "side": "home",
        "bet_line": -1.5,
        "ev_per_unit": 0.0736,
        "win_prob_lb10": 0.513,
        "conviction_sources": 0,
        "is_smart_risk": True,
        "risk_tier": "SMART_RISK",
        "movement_tags": ["smart_risk_high_return", "sharp_price_edge"],
    }
    assert compute_top6_quality_score(core_3of3) > compute_top6_quality_score(smart_risk_zero_agree)


def test_1h_early_season_requires_consensus_and_penalizes_heavy_juice(monkeypatch):
    model = NCAAMMarketFirstModelV2()
    now_iso = datetime.now(timezone.utc).isoformat()
    snap = {
        "spread_home": -2.0,
        "spread_price_home": -110,
        "total": 146.0,
        "_quote_as_of": now_iso,
        "_raw_snaps": [
            {"market_type": "SPREAD_1H", "side": "HOME", "line_value": -1.0, "price": -110, "book": "DraftKings", "captured_at": now_iso},
            {"market_type": "TOTAL_1H", "side": "OVER", "line_value": 66.5, "price": -120, "book": "FanDuel", "captured_at": now_iso},
        ],
    }
    ev = {"id": "evt_1h_nov", "home_team": "Home", "away_team": "Away"}

    # Zero-consensus early season blocks 1H under normal gates even with strong 1H edge
    recs_no_cons = model._generate_recommendations(
        mu_s=-6.0,
        sig_s=10.5,
        mu_t=152.0,
        sig_t=14.0,
        snap=snap,
        event=ev,
        torvik_view={"lean": "Home"},
        relax_gates=False,
        model_ctx={"game_month": 11, "min_rec_games": 4, "is_early_season": True, "agree_count": 0, "agree_count_total": 0},
    )
    assert not any(r["market"] in ("SPREAD_1H", "TOTAL_1H") for r in recs_no_cons)

    # With 2-model consensus and modest total edge over -120 juice, heavy juice (-120 -> +1.0% hurdle) + early bump (+1.0% hurdle) trims marginal -120 1H OVER
    recs_marginal_juice = model._generate_recommendations(
        mu_s=-2.0,
        sig_s=10.5,
        mu_t=150.2,
        sig_t=14.0,
        snap=snap,
        event=ev,
        torvik_view={"lean": "Home"},
        relax_gates=False,
        model_ctx={"game_month": 11, "min_rec_games": 4, "is_early_season": True, "agree_count": 2, "agree_count_total": 2},
    )
    assert not any(r["market"] == "TOTAL_1H" for r in recs_marginal_juice)
