"""Unit tests for injury pricing, RLM split confirmation, correlation Decimal safety,
today-scoped board health, Moneyline CLV SQL, walk-forward weight tuning, and JSON sanitization.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
import sys
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.models.ncaam_market_first_model_v2 import NCAAMMarketFirstModelV2
from src.scripts.backtest_ncaam_model import recommend_weights_walkforward
from src.scripts.board_health import status_from_health
from src.scripts.build_daily_top_picks import upsert_pick
from src.services.correlation.ncaam_correlation_engine import NCAAMCorrelationEngine
from src.services.grading_service import GradingService
from src.services.injury_service import InjuryService


def test_injury_service_kenpom_player_impact_and_bounds():
    svc = InjuryService()

    # Star home scorer OUT with KenPom player metrics shifts spread + toward home dog & lowers total
    res = svc.evaluate_injuries(
        [{"team": "Duke", "player": "Cooper Flagg", "status": "Out", "position": "F"}],
        "Duke",
        "North Carolina",
        home_players=[
            {"player_name": "Cooper Flagg", "metrics": {"min_pct": 85, "usg": 32, "ortg": 124, "ppg": 20.5}},
        ],
    )
    assert res["has_injuries"] is True
    assert res["home_impact_pts"] > 2.0
    assert res["away_impact_pts"] == 0.0
    assert 0.0 < res["spread_adj"] <= 3.0
    assert -3.0 <= res["total_adj"] < 0.0
    assert res["impact_players"][0]["player"] == "Cooper Flagg"

    # Multi-star out cannot exceed +/- 3.0 spread or -3.0 total guardrail
    capped = svc.evaluate_injuries(
        [
            {"team": "Duke", "player": "Starter One", "status": "Out", "position": "G"},
            {"team": "Duke", "player": "Starter Two", "status": "Out", "position": "C"},
            {"team": "Duke", "player": "Starter Three", "status": "Out", "position": "F"},
        ],
        "Duke",
        "North Carolina",
        home_players=[
            {"player_name": "Starter One", "metrics": {"min_pct": 85, "usg": 30, "ppg": 20.0}},
            {"player_name": "Starter Two", "metrics": {"min_pct": 80, "usg": 27, "ppg": 17.5}},
            {"player_name": "Starter Three", "metrics": {"min_pct": 75, "usg": 24, "ppg": 15.0}},
        ],
    )
    assert -3.0 <= capped["spread_adj"] <= 3.0
    assert -3.0 <= capped["total_adj"] <= 0.0

    # Positional fallback works when no KenPom roster metrics are supplied
    fallback = svc.evaluate_injuries(
        [{"team": "North Carolina", "player": "Reserve Guard", "status": "Questionable", "position": "G"}],
        "Duke",
        "North Carolina",
    )
    assert fallback["away_impact_pts"] > 0.0
    assert fallback["spread_adj"] < 0.0


def test_split_and_rlm_confirmation_boost_and_injury_tag():
    model = NCAAMMarketFirstModelV2()
    recs = [{"market": "SPREAD", "side": "AWAY", "ev": 0.03, "movement_tags": []}]
    splits = {
        "SPREAD": {
            "AWAY": {"bet_pct": 26, "handle_pct": 66},
            "HOME": {"bet_pct": 74, "handle_pct": 34},
        }
    }
    mc_info = {"open_spread_home": -4.5, "current_spread_home": -3.5}  # Moved +1.0 toward AWAY

    out = model._apply_split_and_injury_signals(
        recs,
        action_splits=splits,
        injury_context={"spread_adj": 0.9, "has_injuries": True},
        market_consensus=mc_info,
    )
    assert len(out) == 1
    assert "sharp_backing" in out[0]["movement_tags"]
    assert "rlm_confirmed" in out[0]["movement_tags"]
    assert "injury_line_adjusted" in out[0]["movement_tags"]
    assert out[0]["ev"] == pytest.approx(0.035, abs=1e-4)


def test_correlation_engine_handles_postgres_decimals():
    eng = NCAAMCorrelationEngine()
    eng.MIN_SAMPLE_SIZE = 2

    rows = [
        {
            "home_pace": Decimal("71.5"),
            "away_pace": Decimal("70.5"),
            "home_net_eff": Decimal("21.0"),
            "away_net_eff": Decimal("12.0"),
            "close_spread": Decimal("-5.5"),
            "close_total": Decimal("145.5"),
            "margin": Decimal("8"),
            "total_score": Decimal("150"),
        },
        {
            "home_pace": Decimal("71.5"),
            "away_pace": Decimal("70.5"),
            "home_net_eff": Decimal("21.0"),
            "away_net_eff": Decimal("12.0"),
            "close_spread": Decimal("-5.5"),
            "close_total": Decimal("145.5"),
            "margin": Decimal("2"),
            "total_score": Decimal("138"),
        },
    ]

    # Pure-Python list[dict] path (used on Vercel serverless runtime)
    binned_py = eng.build_archetype_bins(rows)
    assert isinstance(binned_py, list) and len(binned_py) == 2
    metrics_py = eng.compute_metrics(binned_py)
    assert any(v.get("status") == "valid" for v in metrics_py.values())

    # Legacy DataFrame path
    binned_df = eng.build_archetype_bins(pd.DataFrame(rows))
    assert len(binned_df) == 2
    metrics_df = eng.compute_metrics(binned_df)
    assert isinstance(metrics_df, dict)
    assert any(v.get("status") == "valid" for v in metrics_df.values())


def test_board_health_separates_today_from_three_day_window():
    # Today (days=1) 100% covered even if future 3-day window has >40% missing totals -> OK
    h_ok = {
        "events_total": 40,
        "with_spread": 20,
        "with_total": 20,
        "missing_total_pct": 0.50,
        "today_events_total": 10,
        "today_with_spread": 10,
        "today_with_total": 10,
        "today_missing_total_pct": 0.0,
    }
    assert status_from_health(h_ok) == "ok"

    # Today missing > 40% totals -> ALERT
    h_alert = {
        **h_ok,
        "today_events_total": 10,
        "today_with_spread": 10,
        "today_with_total": 4,
        "today_missing_total_pct": 0.60,
    }
    assert status_from_health(h_alert) == "alert"


def test_grading_clv_sql_includes_moneyline_implied_prob():
    svc = GradingService()
    mock_conn = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = mock_conn

    with patch("src.services.grading_service.get_db_connection", return_value=mock_ctx), \
         patch("src.services.grading_service._exec") as mock_exec:
        mock_exec.return_value.rowcount = 2
        updated = svc._compute_clv_for_started_games(max_rows=100, lookback_days=3)

    assert updated == 2
    sql_executed = mock_exec.call_args[0][1]
    assert "m.market_type='MONEYLINE' AND m.close_price IS NULL" in sql_executed
    assert "odds_snapshot_ml_prob_before_tip" in sql_executed


def test_walkforward_weight_recommendation_thresholds_and_folds():
    # Insufficient sample stays strictly non-destructive
    small = recommend_weights_walkforward(
        [{"start_time": "2026-11-01T18:00:00Z", "close_spread": -4.5, "final_margin": 6.0}] * 20,
        min_bets=75,
    )
    assert small["status"] == "insufficient_sample"
    assert small["non_destructive"] is True
    assert small["recommended_weights"] is None

    # Synthetic 100-game edge series where KenPom carries true signal
    records = []
    for idx in range(100):
        day = (idx % 28) + 1
        sign = 1.0 if idx % 2 == 0 else -1.0
        records.append({
            "event_id": f"g_{idx}",
            "start_time": f"2026-11-{day:02d}T19:00:00Z",
            "close_spread": -4.0,
            "mu_market_spread": -4.0,
            "diff_torvik": 0.0,
            "diff_kenpom": -10.0 * sign,
            "diff_hasla": -6.0 * sign,
            "other_adj": 0.0,
            "spread_price_home": -110,
            "spread_price_away": -110,
            "final_margin": 4.0 + (7.0 * sign),
        })

    out = recommend_weights_walkforward(records, min_bets=75, min_edge=1.5)
    assert out["non_destructive"] is True
    assert out["n_games"] == 100
    assert len(out["folds"]) == 3


def test_upsert_pick_sanitizes_raw_datetime_serialization_errors():
    mock_conn = MagicMock()
    res = {
        "model_version": "ncaam_market_first_v2",
        "recommendations": [],
        "block_reason": "Object of type datetime is not JSON serializable",
        "context_json": {"captured_at": datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)},
    }
    with patch("src.scripts.build_daily_top_picks._exec") as mock_exec:
        upsert_pick("2026-11-13", "evt_err_1", res, conn=mock_conn)

    params = mock_exec.call_args[0][2]
    assert "JSON serializable" not in (params["reason"] or "")
    assert "unavailable" in (params["reason"] or "").lower()


def test_correlations_game_endpoint_sql_has_no_unescaped_percent_and_returns_200(monkeypatch):
    from fastapi.testclient import TestClient
    from src.api import app
    from src.config import settings

    row_data = {
        "id": "action:ncaam:297763",
        "start_time": datetime(2026, 11, 13, 23, 0, tzinfo=timezone.utc),
        "close_spread": Decimal("-6.5"),
        "home_pace": Decimal("71.2"),
        "home_net_eff": Decimal("22.4"),
        "away_pace": Decimal("68.8"),
        "away_net_eff": Decimal("9.6"),
    }
    mock_conn = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = mock_conn
    captured_sql = []

    def _fake_exec(conn, sql, params=None):
        captured_sql.append(sql)
        cur = MagicMock()
        cur.fetchone.return_value = row_data
        return cur

    monkeypatch.setitem(sys.modules, "pandas", None)
    monkeypatch.setitem(sys.modules, "numpy", None)
    monkeypatch.setattr(settings, "BASEMENT_PASSWORD", "test-secret")
    with patch("src.database.get_db_connection", return_value=mock_ctx), \
         patch("src.database._exec", side_effect=_fake_exec):
        client = TestClient(app)
        resp = client.get(
            "/api/ncaam/correlations/game?event_id=action:ncaam:297763",
            headers={"X-BASEMENT-KEY": "test-secret"},
        )

    assert resp.status_code == 200
    assert captured_sql and "'%'" not in captured_sql[0]
    body = resp.json()
    assert body["archetype"]["key"]


def test_parse_kenpom_web_table_paste_with_unicode_minus_and_interleaved_ranks():
    from src.scripts.ingest_kenpom import parse_kenpom_csv_text

    # Mimics copying live HTML table off kenpom.com:
    # - headers omit unnamed rank sub-columns next to ORtg, DRtg, AdjT
    # - negative numbers use Unicode minus \u2212
    pasted = (
        "Rk\tTeam\tConf\tW-L\tNetRtg\tORtg\tDRtg\tAdjT\tLuck\n"
        "1\tDuke 1\tACC\t28-4\t+32.14\t126.1\t1\t94.0\t4\t68.2\t110\t+.020\n"
        "185\tBrown\tIvy\t14-14\t\u22124.15\t103.5\t195\t107.6\t180\t66.4\t240\t\u2212.012\n"
    )
    rows = parse_kenpom_csv_text(pasted)
    assert len(rows) == 2
    assert rows[0]["team_name"] == "Duke"
    assert rows[0]["adj_em"] == pytest.approx(32.14)
    assert rows[0]["adj_o"] == pytest.approx(126.1)
    assert rows[0]["adj_d"] == pytest.approx(94.0)
    assert rows[0]["adj_t"] == pytest.approx(68.2)
    assert rows[1]["team_name"] == "Brown"
    assert rows[1]["adj_em"] == pytest.approx(-4.15)
    assert rows[1]["adj_o"] == pytest.approx(103.5)
    assert rows[1]["adj_d"] == pytest.approx(107.6)
    assert rows[1]["adj_t"] == pytest.approx(66.4)


def test_get_kenpom_status_and_admin_sync_endpoints(monkeypatch):
    from fastapi.testclient import TestClient
    import src.scripts.ingest_kenpom as ik
    import src.scripts.update_data_health as udh
    from src.api import app
    from src.config import settings

    monkeypatch.setattr(settings, "BASEMENT_PASSWORD", "test-secret")
    monkeypatch.setattr(settings, "CRON_SECRET", "cron-secret")
    monkeypatch.delenv("KENPOM_API_KEY", raising=False)
    monkeypatch.delenv("KENPOM_EMAIL", raising=False)
    monkeypatch.delenv("KENPOM_PASSWORD", raising=False)
    monkeypatch.delenv("KENPOM_COOKIE", raising=False)

    class _StatusCursor:
        def __init__(self, sql):
            self._sql = sql

        def fetchone(self):
            if "FROM kenpom_team_ratings_daily" in self._sql:
                return {"asof_date": "2026-04-06", "n": 365}
            if "FROM data_health" in self._sql:
                return {"status": "stale", "notes": '{"asof_date":"2026-04-06"}', "last_success_at": None}
            return None

    class _StatusConn:
        pass

    @contextmanager
    def _fake_db():
        yield _StatusConn()

    with patch("src.scripts.ingest_kenpom.get_db_connection", _fake_db), \
         patch("src.scripts.ingest_kenpom._exec", side_effect=lambda conn, sql, params=None: _StatusCursor(sql)):
        st = ik.get_kenpom_status()

    assert st["active"] is False
    assert st["latest_asof_date"] == "2026-04-06"
    assert st["team_count"] == 365
    assert "prior season" in st["human_summary"]

    sample_api_rows = [
        {
            "TeamName": f"Team {i}",
            "RankAdjEM": i,
            "ConfShort": "ACC",
            "Wins": 20,
            "Losses": 5,
            "AdjEM": 20.0 - i,
            "AdjOE": 115.0,
            "AdjDE": 95.0 + i,
            "AdjTempo": 68.0,
        }
        for i in range(1, 13)
    ]

    class _FakeResp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return sample_api_rows

    monkeypatch.setattr(ik.requests, "get", lambda *a, **kw: _FakeResp())
    monkeypatch.setattr(ik, "ensure_tables", lambda: None)
    monkeypatch.setattr(ik, "upsert_daily", lambda table, asof, rows, keys: len(rows))
    monkeypatch.setattr(udh, "upsert", lambda *a, **kw: None)

    client = TestClient(app)

    # Admin POST /api/admin/kenpom/sync succeeds with API key in body
    resp_sync = client.post(
        "/api/admin/kenpom/sync",
        headers={"X-BASEMENT-KEY": "test-secret"},
        json={"api_key": "kp-secret-test"},
    )
    assert resp_sync.status_code == 200
    body_sync = resp_sync.json()
    assert body_sync["status"] == "ok"
    assert body_sync["method"] == "official_api"
    assert body_sync["rows"] == 12

    import src.services.job_service as js

    class _FakeJobContext:
        def __init__(self, job_name: str):
            self.job_name = job_name
            self.state = {}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            return False

    monkeypatch.setattr(js, "JobContext", _FakeJobContext)

    # Cron /api/jobs/ingest_kenpom uses run_kenpom_sync cleanly when env API key is set
    monkeypatch.setenv("KENPOM_API_KEY", "kp-cron-test")
    resp_cron = client.get(
        "/api/jobs/ingest_kenpom",
        headers={"Authorization": "Bearer cron-secret"},
    )
    assert resp_cron.status_code == 200
    body_cron = resp_cron.json()
    assert body_cron["status"] == "success"
    assert body_cron["teams_count"] == 12
    assert body_cron["method"] == "official_api"

    # Invalid API key (401 from KenPom) maps cleanly to HTTP 400
    class _UnauthorizedResp:
        status_code = 401
        text = "Invalid token"

    monkeypatch.setattr(ik.requests, "get", lambda *a, **kw: _UnauthorizedResp())
    resp_bad = client.post(
        "/api/admin/kenpom/sync",
        headers={"X-BASEMENT-KEY": "test-secret"},
        json={"api_key": "bad-key"},
    )
    assert resp_bad.status_code == 400
    assert "rejected" in resp_bad.json()["detail"].lower()


def test_model_v2_populates_kenpom_fair_total_and_mu_total_final(monkeypatch):
    from datetime import date

    model = NCAAMMarketFirstModelV2()
    model.torvik_service = MagicMock()
    model.torvik_service.get_projection.return_value = {
        "margin": 6.0,
        "official_margin": 6.0,
        "total": 144.0,
        "projected_score": "69-75",
        "lean": "Home",
    }
    model.torvik_service.get_matchup_team_stats.return_value = {
        "game_tempo": 68.5,
        "home": {"luck": 0.0, "continuity": 75.0, "record": "12-4"},
        "away": {"luck": 0.0, "continuity": 70.0, "record": "10-6"},
    }

    model.kenpom_client = MagicMock()
    model.kenpom_client.calculate_kenpom_adjustment.return_value = {
        "spread_adj": 7.5,
        "neutral_margin": 5.0,
        "fair_margin": 7.5,
        "total_adj": 2.4,
        "tempo_expected": 69.0,
        "summary": "Home +7.5",
    }
    model.kenpom_client.get_team_player_agg.return_value = None
    model.kenpom_client.get_team_rating.return_value = {"adj_em": 18.0, "adj_t": 69.0}
    model.kenpom_client.get_home_court.return_value = None
    model.kenpom_client.get_player_stats_for_team.return_value = []

    model.haslametrics_client = MagicMock()
    model.haslametrics_client.calculate_projection.return_value = None

    model.injury_service = MagicMock()
    model.injury_service.get_matchup_injuries.return_value = {"has_injuries": False, "injuries": []}
    model.geo_service = MagicMock()
    model.geo_service.get_altitude_adjustment.return_value = 0.0
    model.geo_service.calculate_distance.return_value = 50.0
    model.news_service = MagicMock()
    model.news_service.get_team_news.return_value = []
    model.news_service.summarize_impact.return_value = ""

    monkeypatch.setattr(model, "_calculate_shooting_regression", lambda *a, **kw: 0.0)
    monkeypatch.setattr(model, "_calculate_situational_spots", lambda *a, **kw: 0.0)
    monkeypatch.setattr(model, "_calculate_fatigue_penalty", lambda *a, **kw: 0.0)
    monkeypatch.setattr(model, "_apply_referee_signal", lambda eid, tot: tot)
    monkeypatch.setattr(model, "_load_winprob_calibration", lambda: {"points": []})

    event = {
        "id": "evt_kp_total_1",
        "home_team": "Clemson Tigers",
        "away_team": "Georgetown Hoyas",
        "start_time": datetime(2026, 11, 13, 19, 0, 0),
    }
    snap = {"spread_home": -5.5, "total": 146.0}
    res = model.analyze("evt_kp_total_1", event_context=event, market_snapshot=snap, relax_gates=True, persist=False)

    assert res["signals"]["kenpom"]["fair_spread_home"] == pytest.approx(-7.5, abs=0.1)
    assert res["signals"]["kenpom"]["fair_total"] == pytest.approx(148.4, abs=0.1)
    assert res["debug"]["mu_total_final"] is not None
    assert res["debug"]["mu_spread_final"] is not None

